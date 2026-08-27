"""Campaign drive+judge controller — module 5 of the Brady-alignment harness.

drive -> judge -> calibrate -> verify are the primitives; this is the industrial
loop over them. Given the frozen claim inventory + run-manifest, it:

  * **plans** N fresh-session re-probes per claim/scenario (spec §8 — the ALIGNED
    band rests on re-probing a fresh session N times, N read from the manifest
    per tier);
  * **drives** each probe's turns through the live backend (a NEW session per
    probe so the app's per-user limiter never conflates them; turns sequential),
    then **judges** the target turn's envelope;
  * **appends** one result line per probe to a resumable JSONL — a resume skips
    probes already completed with a real verdict, but **re-drives NON_VERDICT
    (upstream-error) probes** rather than silently counting them done;
  * enforces a **hard cost kill-switch** — once the ``CostMeter`` trips its
    dollar/call cap, no further probes are driven (in-flight ones finish) and
    the shortfall is logged, never silently truncated.

Pure orchestration over the injected ``drive_fn`` / ``judge_fn`` (real ones by
default, stubbed in tests) — no OpenAI import here; the LLM legs live in
``judge.py`` and are reached through the default ``judge_fn`` closure.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from campaign import drive
from campaign import judge as _judge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Probe planning
# ---------------------------------------------------------------------------


@dataclass
class Probe:
    """One fresh-session re-probe of one scenario of one claim.

    ``turns`` are the literal messages to send in order; ``judge_target_turn``
    is the index of the turn whose envelope gets judged (the last — a
    multi-turn flow is judged on its pivotal final turn).
    """

    claim_id: str
    scenario_idx: int
    probe_idx: int
    turns: list
    tier: str
    judge_target_turn: int


def _tier_n(tier: str, manifest: dict) -> int:
    """N re-probes for ``tier`` (manifest ``N`` map; default 5 for an unknown
    tier so a mistagged claim still gets the lower-tier sample, never zero)."""
    return int((manifest.get("N") or {}).get(tier, 5))


def plan_probes(claims: list, manifest: dict) -> list:
    """Expand every claim -> scenarios -> N probes (flat list, deterministic
    order). N comes from ``manifest['N'][tier]``."""
    probes: list = []
    for c in claims:
        tier = c.get("tier", "important")
        n = _tier_n(tier, manifest)
        for si, sc in enumerate(c.get("scenarios", []) or []):
            turns = list(sc.get("turns", []) or [])
            target = max(len(turns) - 1, 0)
            for pi in range(n):
                probes.append(Probe(c["id"], si, pi, turns, tier, target))
    return probes


# ---------------------------------------------------------------------------
# Cost meter + kill-switch
# ---------------------------------------------------------------------------


class CostMeter:
    """Thread-safe accumulator of spend + underlying-call count, tripping at a
    hard dollar and/or call cap. ``per_turn_cost`` maps a surface (or
    ``"default"``) to the measured $/drive-turn (Phase-0 measurement)."""

    def __init__(self, dollar_cap=None, call_cap=None, per_turn_cost=None):
        self.dollar_cap = dollar_cap
        self.call_cap = call_cap
        self.per_turn_cost = dict(per_turn_cost or {})
        self._spent = 0.0
        self._calls = 0
        self._lock = threading.Lock()

    def charge(self, surface: str, turns: int = 1) -> None:
        unit = self.per_turn_cost.get(surface, self.per_turn_cost.get("default", 0.0))
        with self._lock:
            self._spent += unit * turns
            self._calls += turns

    @property
    def spent(self) -> float:
        return self._spent

    @property
    def calls(self) -> int:
        return self._calls

    def over_cap(self) -> bool:
        if self.dollar_cap is not None and self._spent >= self.dollar_cap:
            return True
        if self.call_cap is not None and self._calls >= self.call_cap:
            return True
        return False


# ---------------------------------------------------------------------------
# Resumable results JSONL
# ---------------------------------------------------------------------------


def _load_done(results_path: str) -> set:
    """Probe keys already completed with a REAL verdict (``ok is True``).
    NON_VERDICT (``ok is False``) rows are deliberately excluded so a resume
    re-drives the upstream-error probes."""
    done: set = set()
    if not os.path.exists(results_path):
        return done
    with open(results_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ok") is True:
                done.add((rec.get("claim_id"), rec.get("scenario_idx"), rec.get("probe_idx")))
    return done


_RESULT_LOCK = threading.Lock()


def _append_result(results_path: str, rec: dict) -> None:
    with _RESULT_LOCK:
        directory = os.path.dirname(results_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(results_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------


def _default_drive_fn(cache_path=None):
    """Build the real drive: a fresh ``Session`` per probe (unique user_id),
    drive every turn sequentially, return the LAST envelope (the judged one).

    For a MULTI-turn probe the returned envelope also carries ``prior_turns`` —
    the preceding ``{message, response}`` exchange — because a multi-turn
    probe's judgeable unit is the EXCHANGE, not its last message. Handing the
    judge the final turn alone makes any rubric about a FLOW undecidable: the
    u3 re-drive scored a correct "Turn 1 asks the mode question -> Turn 2
    supplies it -> app delivers the unit" MISALIGNED @0.95 ("assumes a specific
    grade and writing mode and provides content") purely because Turn 1 was
    invisible; ALIGNED @0.9 once it wasn't. That is wrong in BOTH directions —
    it can hide a real violation as easily as it manufactures a false one.

    The judged envelope is a COPY: ``prior_turns`` is judge-facing metadata and
    is never written back into the per-turn envelopes ``Session`` already cached,
    so drive-cache.jsonl stays a faithful record of what the backend returned.
    Single-turn probes (the overwhelming majority) are returned untouched.
    """
    def _drive(base_url, turns, model, surface):
        sess = drive.Session(base_url, cache_path=cache_path)
        seen: list[tuple] = []
        for turn in turns:
            seen.append((turn, sess.send(turn, model=model)))
        if not seen:
            return None
        last = seen[-1][1]
        if len(seen) == 1:
            return last
        prior = [{"message": m, "response": e.get("response")} for m, e in seen[:-1]]
        return dataclasses.replace(last, raw={**last.raw, "prior_turns": prior})
    return _drive


def run_campaign(claims, manifest, base_url, results_path, *,
                 drive_fn=None, judge_fn=None, budget=None,
                 openai_client=None, cache_path=None, claim_by_id=None):
    """Drive + judge every not-yet-done probe, append results, honor the cap.

    Returns a summary dict ``{planned, skipped, spent, calls}``. ``drive_fn``
    signature is ``(base_url, turns, model, surface) -> Envelope`` (last turn);
    ``judge_fn`` is ``(claim, envelope) -> Verdict``. Both default to the real
    implementations; tests inject stubs. Concurrency parallelizes DISTINCT
    sessions (each probe is its own session) up to
    ``manifest['concurrency']['max_parallel_sessions']``.
    """
    drive_fn = drive_fn or _default_drive_fn(cache_path)
    if judge_fn is None:
        def judge_fn(claim, env):
            return _judge.judge_claim(claim, env, openai_client=openai_client)
    budget = budget if budget is not None else CostMeter()
    claim_by_id = claim_by_id or {c["id"]: c for c in claims}
    model = manifest.get("drive_model", "gpt-5.4")
    max_par = max(1, int((manifest.get("concurrency") or {}).get("max_parallel_sessions", 6)))

    done = _load_done(results_path)
    probes = [p for p in plan_probes(claims, manifest)
              if (p.claim_id, p.scenario_idx, p.probe_idx) not in done]

    skipped = {"n": 0}
    skip_lock = threading.Lock()

    def _run_one(p):
        if budget.over_cap():  # hard kill-switch — do NOT start new work
            with skip_lock:
                skipped["n"] += 1
            return
        claim = claim_by_id[p.claim_id]
        surface = claim.get("surface", "")
        env = drive_fn(base_url, p.turns, model, surface)
        budget.charge(surface, turns=len(p.turns) or 1)
        try:
            v = judge_fn(claim, env)
        except Exception as exc:  # a judge failure must not abort the batch
            v = _judge.Verdict("UNCERTAIN", 0.0, f"judge error: {exc}",
                                claim.get("judge_method", ""), "")
        rec = {
            "claim_id": p.claim_id, "scenario_idx": p.scenario_idx, "probe_idx": p.probe_idx,
            "tier": p.tier, "surface": surface,
            "status": getattr(v, "status", None), "confidence": getattr(v, "confidence", None),
            "rationale": (getattr(v, "rationale", "") or "")[:500],
            "evidence": (getattr(v, "evidence", "") or "")[:500],
            "ok": bool(getattr(env, "ok", True)),
        }
        _append_result(results_path, rec)

    with ThreadPoolExecutor(max_workers=max_par) as ex:
        futures = [ex.submit(_run_one, p) for p in probes]
        for f in as_completed(futures):
            f.result()  # surface any unexpected exception

    if skipped["n"]:
        logger.warning(
            "cost kill-switch tripped: %d probes SKIPPED (spent=%.2f, calls=%d, "
            "dollar_cap=%s, call_cap=%s)",
            skipped["n"], budget.spent, budget.calls, budget.dollar_cap, budget.call_cap,
        )
    return {"planned": len(probes), "skipped": skipped["n"],
            "spent": budget.spent, "calls": budget.calls}
