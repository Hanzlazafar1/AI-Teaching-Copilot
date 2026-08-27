"""Campaign drive client — the verification harness's HTTP front-end to
``/api/chat``.

This is module 1 of 4 (drive → judge → calibrate → verify) for the
Brady-alignment verification campaign (design spec §6). Its single job is to
turn a message into a parsed response *without ever lying about failure*:

  * Upstream trouble — the app's own per-user **429**, provider **503/504**,
    any other non-200, or a ``Timeout`` / ``ConnectionError`` — is a
    **non-verdict**, not an answer. We retry with **capped exponential
    backoff** (base ~1s, hard cap 30s — a server ``Retry-After: 3600`` is
    NEVER honored literally) and, on exhaustion, return an
    ``Envelope(status="NON_VERDICT")``. We **never raise** and **never** let an
    error masquerade as a real (mis)aligned answer.
  * Every ``send`` **appends the raw envelope** (plus ``session_id``,
    ``turn_idx``, ``status``) as one line to an append-only **JSONL cache**, so
    a later re-judge never has to re-drive the (expensive, stochastic) backend.

Each :class:`Session` uses a **unique ``user_id``** (so the app's per-user
rate limiter never conflates two campaign sessions) and runs its turns
**sequentially** via a simple ``turn_idx`` counter.

The module is deliberately transport-thin and unit-tested with mocked HTTP; it
needs no live backend.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import requests

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: POST timeout. A SCRIPTED_ML turn fans out into several OpenAI generations,
#: so a single ``/api/chat`` call can legitimately take a while.
REQUEST_TIMEOUT: float = 120.0

#: Total attempts per ``send`` before giving up with a NON_VERDICT.
MAX_ATTEMPTS: int = 5

#: Exponential-backoff base and hard cap (seconds). The cap is absolute — it
#: bounds the exponential term AND any server ``Retry-After`` hint.
BASE_BACKOFF: float = 1.0
MAX_BACKOFF: float = 30.0

#: The upstream status codes we *expect* to have to ride out (throttle +
#: provider hiccups). We additionally treat ANY non-200 as a retryable
#: non-verdict rather than trust an error body as a real answer.
RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

def _default_cache_path() -> str:
    """Resolve the JSONL cache location at *construction* time (not import).

    Prefers ``$CAMPAIGN_CACHE_PATH`` (the runner points this at the current
    session's scratchpad); otherwise a repo-relative, git-ignored
    ``.campaign_cache.jsonl`` under the CWD. Deliberately NOT a hardcoded
    per-session scratchpad path — that goes stale the moment the session
    changes and would silently write the cache into a dead directory.
    """
    return os.environ.get("CAMPAIGN_CACHE_PATH") or os.path.join(
        os.getcwd(), ".campaign_cache.jsonl"
    )


#: Back-compat module constant (computed once at import from the CWD/env).
#: Prefer passing ``cache_path=`` explicitly or setting ``$CAMPAIGN_CACHE_PATH``.
DEFAULT_CACHE_PATH: str = _default_cache_path()

# Serialize appends so distinct sessions sharing one cache file (low-concurrency
# fan-out, §6) don't interleave partial lines within this process.
_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


@dataclass
class Envelope:
    """A light wrapper over a parsed ``/api/chat`` JSON body.

    Envelope fields (``response``, ``intent``, ``parsed_query``, ``sources``,
    ``retrieved_context``, ``session_state``, ``judge_score``, ``quality``,
    ``follow_up_question``, ``request_id`` …) are reachable as attributes,
    proxied through to :attr:`raw`. The driver-owned metadata
    (:attr:`status`, :attr:`session_id`, :attr:`turn_idx`,
    :attr:`http_status`, :attr:`error`) are real dataclass fields and always
    win over any same-named envelope key.

    ``status`` is ``"OK"`` for a genuine 200 answer and ``"NON_VERDICT"`` for
    an upstream error the campaign must never score.
    """

    raw: dict[str, Any]
    status: str  # "OK" | "NON_VERDICT"
    session_id: str = ""
    turn_idx: int = 0
    http_status: Optional[int] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style access into the raw envelope (never raises)."""
        raw = self.__dict__.get("raw")
        return raw.get(key, default) if isinstance(raw, dict) else default

    def __getattr__(self, name: str) -> Any:
        # Only fires for names not found by normal lookup, so it can't shadow
        # dataclass fields / properties. Proxy into the raw envelope; guard
        # against recursion on internal/dunder names and before ``raw`` exists.
        if name.startswith("_"):
            raise AttributeError(name)
        raw = self.__dict__.get("raw")
        if isinstance(raw, dict) and name in raw:
            return raw[name]
        raise AttributeError(
            f"{type(self).__name__!s} has no attribute {name!r} "
            f"(status={self.__dict__.get('status')!r})"
        )


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------


def _backoff_delay(
    attempt: int,
    retry_after: Optional[float] = None,
    *,
    base: float = BASE_BACKOFF,
    cap: float = MAX_BACKOFF,
) -> float:
    """Capped exponential backoff with equal jitter, in seconds.

    ``base * 2**attempt`` capped at ``cap``. A server ``Retry-After`` hint (if
    any) acts as a *floor* but is itself capped at ``cap`` — we NEVER honor a
    literal ``Retry-After: 3600``. Equal jitter keeps the result within
    ``[delay/2, delay] <= cap`` to avoid thundering-herd retries.
    """
    delay = min(base * (2 ** attempt), cap)
    if retry_after is not None:
        delay = min(max(delay, retry_after), cap)
    jittered = delay / 2.0 + random.uniform(0.0, delay / 2.0)
    return min(jittered, cap)


def _parse_retry_after(resp: Any) -> Optional[float]:
    """Best-effort numeric ``Retry-After`` (seconds). HTTP-date form or a
    missing/garbage header returns ``None`` → fall back to pure backoff."""
    try:
        val = resp.headers.get("Retry-After")
    except Exception:
        return None
    if val is None:
        return None
    try:
        return max(0.0, float(val))
    except (TypeError, ValueError):
        return None


def _safe_text(resp: Any, limit: int = 300) -> str:
    try:
        return (resp.text or "")[:limit]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class Session:
    """A single verification conversation against ``/api/chat``.

    Owns a stable ``session_id`` and a **unique** ``user_id`` (generated when
    not supplied, so the backend's per-user limiter never conflates campaign
    sessions). Turns run sequentially — each :meth:`send` consumes the next
    ``turn_idx``.
    """

    def __init__(
        self,
        base_url: str,
        user_id: Optional[str] = None,
        cache_path: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id if user_id is not None else uuid.uuid4().hex
        self.session_id = uuid.uuid4().hex
        self.cache_path = cache_path or _default_cache_path()
        self.turn_idx = 0

    # -- public ----------------------------------------------------------

    def send(self, message: str, model: str = "gpt-4o") -> Envelope:
        """Drive one turn. Returns an ``OK`` envelope for a real 200 answer,
        or a ``NON_VERDICT`` envelope on retry exhaustion. Never raises."""
        turn_idx = self.turn_idx
        self.turn_idx += 1  # sequential — every send consumes a turn slot

        payload = {
            "message": message,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "model": model,
        }
        url = f"{self.base_url}/api/chat"

        last_status: Optional[int] = None
        last_error: Optional[str] = None

        for attempt in range(MAX_ATTEMPTS):
            is_last = attempt == MAX_ATTEMPTS - 1
            try:
                resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                last_status = None
                last_error = f"{type(exc).__name__}: {exc}"
                if not is_last:
                    time.sleep(_backoff_delay(attempt))
                continue

            status = getattr(resp, "status_code", None)
            if status == 200:
                try:
                    raw = resp.json()
                except ValueError as exc:
                    # 200 with an unparseable body — treat as a retryable glitch.
                    last_status = 200
                    last_error = f"JSONDecodeError: {exc}"
                    if not is_last:
                        time.sleep(_backoff_delay(attempt))
                    continue
                env = Envelope(
                    raw=raw if isinstance(raw, dict) else {"response": raw},
                    status="OK",
                    session_id=self.session_id,
                    turn_idx=turn_idx,
                    http_status=200,
                )
                self._append_cache(env, message=message, model=model)
                return env

            # Any non-200 (incl. RETRYABLE_STATUS) → retryable upstream
            # non-verdict. We never trust an error body as a real answer.
            last_status = status
            last_error = _safe_text(resp)
            if not is_last:
                time.sleep(_backoff_delay(attempt, _parse_retry_after(resp)))

        env = Envelope(
            raw={},
            status="NON_VERDICT",
            session_id=self.session_id,
            turn_idx=turn_idx,
            http_status=last_status,
            error=last_error,
        )
        self._append_cache(env, message=message, model=model)
        return env

    # -- cache -----------------------------------------------------------

    def _append_cache(self, env: Envelope, *, message: str, model: str) -> None:
        """Append one JSONL line: the raw envelope + (session_id, turn_idx,
        status) and enough context to re-judge without re-driving."""
        record = {
            "session_id": env.session_id,
            "turn_idx": env.turn_idx,
            "status": env.status,
            "http_status": env.http_status,
            "error": env.error,
            "user_id": self.user_id,
            "model": model,
            "message": message,
            "envelope": env.raw,
        }
        line = json.dumps(record, ensure_ascii=False)
        directory = os.path.dirname(self.cache_path)
        with _CACHE_LOCK:
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.cache_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
