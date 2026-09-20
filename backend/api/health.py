"""Phase 11.6 — deep health probes.

Two endpoints (wired into ``main.py``):

  * ``/health/live`` — process liveness. Always ``{"status": "ok"}`` unless
    the worker is wedged (Python itself failed to return). Kubernetes uses
    this as the ``livenessProbe`` — a failure restarts the pod.

  * ``/health/ready`` — request-readiness. Runs real probes against Qdrant,
    the ML library index, and OpenAI. Used for the ``readinessProbe`` and
    for load-balancer health checks — a failure takes the pod OUT OF ROTATION
    but does NOT restart it (because the dependency is likely external and
    restarts don't help).

Each probe is cached for ``PROBE_CACHE_TTL`` seconds so that a
load-balancer hammering readiness at 1Hz doesn't translate into 1Hz OpenAI
embedding calls. A freshly-failed probe expires the cache immediately on the
next call (the cache only caches successes) so we recover from brief outages
as soon as the upstream comes back.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

PROBE_CACHE_TTL = 30.0  # seconds
# Per-probe timeout. Kept tight so a single probe can't block the readiness
# endpoint for the load balancer longer than its poll interval.
PROBE_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Probe result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    """One probe's outcome. ``ok=False`` means the subsystem is unavailable."""

    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


# ---------------------------------------------------------------------------
# Individual probes — each returns a ProbeResult and never raises.
# ---------------------------------------------------------------------------


async def _probe_qdrant() -> ProbeResult:
    """Fetch the configured collection info — proves we can reach Qdrant and
    that our collection exists."""
    try:
        from retrieval.search import COLLECTION_NAME, get_qdrant_client

        client = get_qdrant_client()
        await asyncio.wait_for(
            client.get_collection(COLLECTION_NAME),
            timeout=PROBE_TIMEOUT,
        )
        return ProbeResult("qdrant", ok=True)
    except asyncio.TimeoutError:
        return ProbeResult("qdrant", ok=False, detail="timeout")
    except Exception as exc:
        return ProbeResult("qdrant", ok=False, detail=f"{type(exc).__name__}: {exc}")


def _probe_library_index() -> ProbeResult:
    """The ML library's embedding index must be loadable — otherwise
    library_precheck falls back to SKIP on every request and the product
    degrades silently. Better to fail readiness now."""
    try:
        from retrieval.ml_library import get_library

        lib = get_library()
        count = len(getattr(lib, "entries", []) or [])
        if count == 0:
            return ProbeResult("library_index", ok=False, detail="empty library")
        return ProbeResult("library_index", ok=True, detail=f"{count} entries")
    except FileNotFoundError as exc:
        return ProbeResult(
            "library_index", ok=False, detail=f"index missing: {exc}"
        )
    except Exception as exc:
        return ProbeResult(
            "library_index", ok=False,
            detail=f"{type(exc).__name__}: {exc}",
        )


_openai_probe_client: AsyncOpenAI | None = None


def _get_openai_probe_client() -> AsyncOpenAI:
    """Isolated client for health probes so its retry budget / timeout don't
    share state with the generation clients."""
    global _openai_probe_client
    if _openai_probe_client is None:
        kwargs = {"api_key": settings.effective_api_key, "timeout": PROBE_TIMEOUT}
        if settings.effective_base_url:
            kwargs["base_url"] = settings.effective_base_url
        _openai_probe_client = AsyncOpenAI(**kwargs)
    return _openai_probe_client


async def _probe_openai() -> ProbeResult:
    """Tiny embedding call to verify OpenAI reachability + our API key is
    valid. Cached 30s so 1-per-second probe traffic translates to 2 calls
    per minute, not 60."""
    try:
        client = _get_openai_probe_client()
        # 1-character input keeps the cost/latency trivially small.
        await asyncio.wait_for(
            client.embeddings.create(
                model=settings.openai_embedding_model,
                input="x",
            ),
            timeout=PROBE_TIMEOUT,
        )
        return ProbeResult("openai", ok=True)
    except asyncio.TimeoutError:
        return ProbeResult("openai", ok=False, detail="timeout")
    except Exception as exc:
        return ProbeResult(
            "openai", ok=False,
            detail=f"{type(exc).__name__}",
        )


# ---------------------------------------------------------------------------
# Success cache — only successful probes are cached. A failing probe is
# re-run every call so we recover from brief outages without waiting out
# the cache TTL.
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    result: ProbeResult
    expires_at: float


_cache: dict[str, _CacheEntry] = {}


async def _cached(
    name: str,
    runner: Callable[[], Awaitable[ProbeResult]] | Callable[[], ProbeResult],
) -> ProbeResult:
    """Run ``runner`` and cache a *successful* result for ``PROBE_CACHE_TTL``.

    Sync and async runners both supported — the library_index probe is sync
    while the others are async. Caching the success side only is deliberate:
    we want readiness to flip back to green the *instant* an outage clears,
    not 30 seconds after.
    """
    now = time.monotonic()
    entry = _cache.get(name)
    if entry is not None and entry.expires_at > now and entry.result.ok:
        return entry.result

    result_or_awaitable = runner()
    if asyncio.iscoroutine(result_or_awaitable):
        result = await result_or_awaitable
    else:
        result = result_or_awaitable  # type: ignore[assignment]

    if result.ok:
        _cache[name] = _CacheEntry(result, now + PROBE_CACHE_TTL)
    else:
        _cache.pop(name, None)
    return result


# ---------------------------------------------------------------------------
# Public entry point — used by the /health/ready route in main.py.
# ---------------------------------------------------------------------------


async def run_readiness_probes() -> tuple[bool, list[ProbeResult]]:
    """Run all probes in parallel. Returns ``(overall_ok, per_probe_results)``.

    Parallel so the total latency of readiness is ``max(probe_latency)`` not
    ``sum(probe_latency)``. Overall readiness is ``all(ok)``.
    """
    results = await asyncio.gather(
        _cached("qdrant", _probe_qdrant),
        _cached("library_index", _probe_library_index),
        _cached("openai", _probe_openai),
    )
    overall_ok = all(r.ok for r in results)
    if not overall_ok:
        failing = [r.name for r in results if not r.ok]
        logger.warning("Readiness probe failed: %s", ", ".join(failing))
    return overall_ok, list(results)


def _reset_probe_cache_for_tests() -> None:
    """Test-only hook — lets unit tests clear cached success state between
    runs without reaching into module globals from the test file."""
    _cache.clear()
