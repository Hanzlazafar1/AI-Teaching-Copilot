"""Campaign calibration gate — measure the judge against Brady's DOCUMENTED
ground truth and BLOCK the run if it is too willing to say ALIGNED.

Module 3 of 4 (drive → judge → **calibrate** → verify) for the Brady-alignment
verification campaign (design spec §7 "Judge control"). The campaign judge is
gpt-4o @ temp 0; self-consistency detects *variance* but not *bias*. Bias in
the one direction that matters — calling a Brady-**misaligned** response
ALIGNED (a false-ALIGNED) — is caught here, by scoring the judge against a
hand-curated gold set of examples taken from Brady's own documented rules
(feedback-7-july.md / requirements.md / decisions.md; each item cites its
``source_quote``).

The gate (spec §7, §10 manifest): the **false-ALIGNED rate is a pre-registered
BLOCKING threshold** — pilot value **0.0**. ``calibrate`` returns
``halt=True`` when ``false_aligned_rate > threshold`` and hands back the
offending items so the report can name them. false-MISALIGNED (the judge being
too strict) is recorded but **never halts** — an over-cautious judge is safe;
an over-permissive one certifies a defect.

**How each gold item is judged.** ``calibrate`` reconstructs the same inputs
the live judge sees: it wraps the item into a synthetic :class:`drive.Envelope`
(the ``response`` — a flat string, or a structured lesson dict for lesson-shape
claims like E1/Step-3 — plus the ``parsed_query`` grade/mode/query_type and the
``sources`` a launch-first check needs) and builds a ``claim`` dict from the
item's ``claim_type``/``judge_method``/``observable``. It then calls the passed
``judge_fn(claim, env)``. Tests inject a stub ``judge_fn``; the pilot injects
``judge.judge_claim`` (via a small closure or ``openai_client=``).

By design the **blocking** side of the gold set (every misaligned item) is
**deterministic or launch-first** — judged with zero LLM involvement — so the
false-ALIGNED gate rests on crisp, reproducible ground truth rather than
stochastic model output. The LLM-judged items in the set are all *aligned*
examples (they document §0 / 2A-2B / U2 claim types and can never trip the
false-ALIGNED halt); they exercise the judge only when a real client is wired.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from campaign import drive

# ---------------------------------------------------------------------------
# Gold set location + schema
# ---------------------------------------------------------------------------

#: The Brady-documented gold set (one JSON object per line).
GOLD_PATH: str = os.path.join(os.path.dirname(__file__), "gold", "brady_gold.jsonl")

#: Keys every gold line must carry. ``response`` (a structured lesson dict) is
#: an OPTIONAL extra for lesson-shape claims; ``grade``/``mode``/``query_type``/
#: ``sources``/``rubric`` are optional context threaded into the envelope/claim.
REQUIRED_KEYS: tuple[str, ...] = (
    "claim_id",
    "claim_type",
    "judge_method",
    "observable",
    "response_text",
    "brady_label",
    "source_quote",
)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class CalibrationResult:
    """Outcome of scoring a judge against the gold set.

    ``false_aligned_rate`` is the campaign's certainty ceiling: the fraction of
    the WHOLE gold set the judge called ALIGNED while Brady's documented label
    is *misaligned*. ``halt`` fires when it **exceeds** ``threshold`` (a strict
    ``>``: a rate equal to the threshold passes). ``offenders`` are exactly the
    false-ALIGNED items, annotated with the verdict, for the report.
    UNCERTAIN counts toward neither error rate; it is tracked in
    ``n_uncertain``.
    """

    n: int
    false_aligned: int
    false_misaligned: int
    n_uncertain: int
    false_aligned_rate: float
    false_misaligned_rate: float
    threshold: float
    halt: bool
    offenders: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gold loading
# ---------------------------------------------------------------------------


def load_gold(path: Optional[str] = None) -> list[dict]:
    """Load the gold set as a list of dicts (skips blank lines). Raises on a
    malformed line so a corrupt gold set fails loudly rather than silently
    shrinking the calibration sample."""
    path = path or GOLD_PATH
    items: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise ValueError(f"{path}:{lineno}: invalid JSON — {exc}") from exc
    return items


# ---------------------------------------------------------------------------
# Envelope / claim reconstruction — give the judge the SAME inputs it sees live
# ---------------------------------------------------------------------------


def _build_envelope(item: dict) -> "drive.Envelope":
    """Wrap a gold item into a synthetic OK envelope.

    ``response`` is the item's structured lesson dict when present (E1/Step-3
    need the MiniLesson shape) else its flat ``response_text``. Grade / mode /
    query_type ride in ``parsed_query`` (where the judge's extractors look);
    ``sources`` rides through verbatim for the launch-first provenance check.
    """
    resp = item.get("response")
    if resp is None:
        resp = item.get("response_text", "")
    raw: dict[str, Any] = {"response": resp}

    # #56 — a multi-turn gold item carries the earlier exchange, exactly as the
    # drive now hands it to the judge. This is what lets the gold set exercise
    # (and BLOCK) the leniency direction: showing the judge that Turn 1 behaved
    # must never excuse a Turn 2 that breaks the rubric.
    if item.get("prior_turns"):
        raw["prior_turns"] = item["prior_turns"]

    parsed_query: dict[str, Any] = {}
    if item.get("grade") is not None:
        parsed_query["grade_level"] = str(item["grade"])
    if item.get("mode") is not None:
        parsed_query["writing_mode"] = item["mode"]
    if item.get("query_type") is not None:
        parsed_query["query_type"] = item["query_type"]
    if parsed_query:
        raw["parsed_query"] = parsed_query

    if item.get("sources") is not None:
        raw["sources"] = item["sources"]

    return drive.Envelope(raw=raw, status="OK")


def _build_claim(item: dict) -> dict:
    """Build the claim dict the judge dispatches on. Threads the optional
    grade/mode/query_type/rubric overrides plus ``claim_id`` (harmless to the
    judge — it ignores unknown keys — and used by calibrate for traceability)."""
    claim: dict[str, Any] = {
        "claim_id": item.get("claim_id"),
        "judge_method": item.get("judge_method"),
        "observable": item.get("observable"),
    }
    for key in ("grade", "mode", "query_type", "rubric"):
        if item.get(key) is not None:
            claim[key] = item[key]
    return claim


def _verdict_status(verdict: Any) -> Optional[str]:
    """Read an uppercased status from a Verdict (or a dict-shaped verdict)."""
    status = getattr(verdict, "status", None)
    if status is None and isinstance(verdict, dict):
        status = verdict.get("status")
    return status.strip().upper() if isinstance(status, str) else None


def _offender(item: dict, verdict: Any) -> dict:
    """A report row for one false-ALIGNED item."""
    return {
        "claim_id": item.get("claim_id"),
        "claim_type": item.get("claim_type"),
        "judge_method": item.get("judge_method"),
        "observable": item.get("observable"),
        "brady_label": item.get("brady_label"),
        "verdict_status": _verdict_status(verdict),
        "rationale": getattr(verdict, "rationale", ""),
        "source_quote": item.get("source_quote"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calibrate(
    judge_fn: Callable[..., Any],
    gold: list[dict],
    *,
    threshold: float = 0.0,
    openai_client: Any = None,
) -> CalibrationResult:
    """Score ``judge_fn`` against ``gold`` and decide whether to HALT.

    For each gold item: reconstruct the judge's inputs (:func:`_build_envelope`
    + :func:`_build_claim`) and call ``judge_fn(claim, env)`` — or, when an
    ``openai_client`` is supplied (real judge), ``judge_fn(claim, env,
    openai_client=client)`` so the LLM legs can run.

    Error accounting (over the WHOLE set as denominator):
      * **false_aligned** — verdict ALIGNED but ``brady_label == "misaligned"``
        (the dangerous direction; drives ``halt``).
      * **false_misaligned** — verdict MISALIGNED but ``brady_label ==
        "aligned"`` (recorded, never halts).
      * UNCERTAIN / unknown — ``n_uncertain`` (counts toward neither error).

    ``halt`` iff ``false_aligned_rate > threshold`` (strict; pilot threshold
    0.0). Returns a :class:`CalibrationResult` carrying the rates and the
    false-ALIGNED ``offenders``.
    """
    n = 0
    false_aligned = 0
    false_misaligned = 0
    n_uncertain = 0
    offenders: list[dict] = []

    for item in gold:
        env = _build_envelope(item)
        claim = _build_claim(item)
        if openai_client is not None:
            verdict = judge_fn(claim, env, openai_client=openai_client)
        else:
            verdict = judge_fn(claim, env)

        status = _verdict_status(verdict)
        label = str(item.get("brady_label", "")).strip().lower()
        n += 1

        if status == "ALIGNED":
            if label == "misaligned":
                false_aligned += 1
                offenders.append(_offender(item, verdict))
        elif status == "MISALIGNED":
            if label == "aligned":
                false_misaligned += 1
        else:  # UNCERTAIN or an unrecognized status — neither error direction.
            n_uncertain += 1

    false_aligned_rate = false_aligned / n if n else 0.0
    false_misaligned_rate = false_misaligned / n if n else 0.0

    return CalibrationResult(
        n=n,
        false_aligned=false_aligned,
        false_misaligned=false_misaligned,
        n_uncertain=n_uncertain,
        false_aligned_rate=false_aligned_rate,
        false_misaligned_rate=false_misaligned_rate,
        threshold=threshold,
        halt=false_aligned_rate > threshold,
        offenders=offenders,
    )
