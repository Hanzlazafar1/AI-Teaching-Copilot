"""Unit tests for the campaign calibration gate (``campaign/calibrate.py``).

Module 3 of 4 (drive → judge → **calibrate** → verify). Calibration measures
the campaign judge against a **Brady-DOCUMENTED gold set** and blocks the run
when the judge's **false-ALIGNED rate** (the dangerous direction — calling a
Brady-misaligned response ALIGNED) exceeds a pre-registered threshold
(spec §7 "Judge control"; pilot threshold = 0.0).

These tests are fully deterministic:

  * the calibrate-logic tests use **stub** ``judge_fn``s (lenient / perfect /
    strict / uncertain) so no OpenAI is ever touched;
  * one integration test runs the **real** ``judge.judge_claim`` over the
    deterministic + launch-first slice of the shipped gold set with a
    ``_BoomOpenAI`` that raises if the LLM is reached — proving that slice
    calibrates to **zero false-ALIGNED offline**.

They belong in the always-run gate.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from campaign import calibrate
from campaign import judge

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Stubs — controllable stand-in judges. No real network / key is ever touched.
# ---------------------------------------------------------------------------


def _verdict(status: str):
    return judge.Verdict(status, 1.0, f"stub:{status}", "stub", "")


def _lenient_judge(claim, env):
    """Always ALIGNED — the dangerous judge the gate exists to catch."""
    return _verdict("ALIGNED")


def _strict_judge(claim, env):
    """Always MISALIGNED — drives the false_misaligned (non-halting) side."""
    return _verdict("MISALIGNED")


def _uncertain_judge(claim, env):
    """Always UNCERTAIN — counts as neither aligned nor misaligned."""
    return _verdict("UNCERTAIN")


def _make_perfect_judge(gold):
    """A judge that returns each item's TRUE Brady label (keyed by claim_id,
    which ``calibrate`` threads into the claim dict)."""
    by_id = {g["claim_id"]: g["brady_label"] for g in gold}

    def _judge(claim, env):
        label = by_id[claim["claim_id"]]
        return _verdict("ALIGNED" if label == "aligned" else "MISALIGNED")

    return _judge


class _BoomOpenAI:
    """Any use of the LLM raises — proves the deterministic / launch-first
    slice of the gold set never reaches for the model."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(parse=self._boom)
        )

    def _boom(self, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("LLM must not be called on the deterministic slice")


# A 4-item in-test gold list (2 aligned, 2 misaligned). Content is irrelevant
# to the stub judges — these tests pin the calibrate ARITHMETIC.
_GOLD4 = [
    {"claim_id": "a1", "claim_type": "banned", "judge_method": "deterministic",
     "observable": "validate_no_forbidden_words", "response_text": "clean one",
     "brady_label": "aligned", "source_quote": "q"},
    {"claim_id": "a2", "claim_type": "e1", "judge_method": "deterministic",
     "observable": "validate_grade_band_close", "response_text": "clean two",
     "brady_label": "aligned", "source_quote": "q"},
    {"claim_id": "m1", "claim_type": "banned", "judge_method": "deterministic",
     "observable": "validate_no_forbidden_words", "response_text": "discuss it",
     "brady_label": "misaligned", "source_quote": "q"},
    {"claim_id": "m2", "claim_type": "n2", "judge_method": "deterministic",
     "observable": "validate_story_only_narrative", "response_text": "a story",
     "brady_label": "misaligned", "source_quote": "q"},
]


# ---------------------------------------------------------------------------
# Calibrate arithmetic
# ---------------------------------------------------------------------------


def test_lenient_judge_false_aligns_both_misaligned_items_and_halts():
    res = calibrate.calibrate(_lenient_judge, _GOLD4)
    assert res.n == 4
    # Both misaligned items were falsely ALIGNED → 2/4.
    assert res.false_aligned == 2
    assert res.false_aligned_rate == 0.5
    # Pilot threshold is 0.0 → any false-ALIGN halts.
    assert res.halt is True
    # Both offenders captured, by id.
    assert {o["claim_id"] for o in res.offenders} == {"m1", "m2"}
    # The aligned items were correctly ALIGNED → no false_misaligned.
    assert res.false_misaligned == 0


def test_perfect_judge_has_zero_false_aligned_and_no_halt():
    res = calibrate.calibrate(_make_perfect_judge(_GOLD4), _GOLD4)
    assert res.n == 4
    assert res.false_aligned_rate == 0.0
    assert res.false_misaligned_rate == 0.0
    assert res.halt is False
    assert res.offenders == []


def test_threshold_is_a_param_and_gates_strictly_greater_than():
    # false_aligned_rate is exactly 0.5.
    at = calibrate.calibrate(_lenient_judge, _GOLD4, threshold=0.5)
    assert at.false_aligned_rate == 0.5
    assert at.halt is False  # 0.5 > 0.5 is False — threshold is a ceiling met, not exceeded.
    below = calibrate.calibrate(_lenient_judge, _GOLD4, threshold=0.4)
    assert below.halt is True


def test_uncertain_counts_as_neither_and_never_halts():
    res = calibrate.calibrate(_uncertain_judge, _GOLD4)
    assert res.false_aligned == 0
    assert res.false_aligned_rate == 0.0
    assert res.n_uncertain == 4
    assert res.halt is False


def test_strict_judge_drives_false_misaligned_not_a_halt():
    res = calibrate.calibrate(_strict_judge, _GOLD4)
    # The two aligned items were wrongly MISALIGNED.
    assert res.false_misaligned == 2
    assert res.false_misaligned_rate == 0.5
    # But false_misaligned never halts the campaign — only false_aligned does.
    assert res.false_aligned_rate == 0.0
    assert res.halt is False


def test_empty_gold_is_safe():
    res = calibrate.calibrate(_lenient_judge, [])
    assert res.n == 0
    assert res.false_aligned_rate == 0.0
    assert res.halt is False


# ---------------------------------------------------------------------------
# The shipped Brady-documented gold set
# ---------------------------------------------------------------------------


def test_brady_gold_loads_as_valid_jsonl_with_required_keys():
    # Read the file RAW so this asserts genuine JSONL (one JSON object / line).
    with open(calibrate.GOLD_PATH, encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip()]
    assert 15 <= len(lines) <= 25, f"expected ~15-20 gold items, got {len(lines)}"

    required = set(calibrate.REQUIRED_KEYS)
    seen_ids: set[str] = set()
    for ln in lines:
        item = json.loads(ln)  # raises on invalid JSON → fails the test
        assert required <= set(item), f"missing keys: {required - set(item)}"
        assert item["brady_label"] in {"aligned", "misaligned"}
        assert item["source_quote"].strip(), "source_quote must be non-empty (Brady provenance)"
        # A judgeable response must exist (structured lesson OR flat text).
        assert item.get("response") or item["response_text"]
        seen_ids.add(item["claim_id"])
    assert len(seen_ids) == len(lines), "claim_id values must be unique"


def test_load_gold_returns_the_same_items():
    gold = calibrate.load_gold()
    assert len(gold) >= 15
    # Both labels are represented (a one-sided gold set can't calibrate).
    labels = {g["brady_label"] for g in gold}
    assert labels == {"aligned", "misaligned"}


def test_real_judge_over_deterministic_slice_has_zero_false_aligned_offline():
    """The load-bearing pilot gate: the REAL judge, over the deterministic +
    launch-first slice of the Brady gold set, produces ZERO false-ALIGNED
    (and, because that slice is crisply grounded, zero false-misaligned) with
    the LLM wired to explode — no network, always-run-safe."""
    gold = [g for g in calibrate.load_gold()
            if g["judge_method"] in ("deterministic", "launch-first")]
    assert len(gold) >= 12, "the offline slice should carry most of the gate"
    boom = _BoomOpenAI()

    def _real(claim, env):
        return judge.judge_claim(claim, env, openai_client=boom)

    res = calibrate.calibrate(_real, gold)
    assert res.false_aligned == 0, res.offenders
    assert res.false_misaligned == 0
    assert res.n_uncertain == 0, "every deterministic gold item should be decisively judged"
    assert res.halt is False
