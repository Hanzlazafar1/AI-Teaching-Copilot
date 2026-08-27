"""Offline golden-master: the committed Brady baseline must satisfy every
Protected-Set invariant. Fast (reads JSON, no server/LLM) — runs in the
always-on gate. Guards both the checkers and the baseline artifact.
See implementation-strategy.md §1c.
"""
import json
from pathlib import Path

from tests.protected_invariants import CHECKERS, check_all
from tests.protected_set import PROTECTED_SET

_BASELINE = Path(__file__).resolve().parents[2] / "tests" / "golden" / "baseline-2026-07-17.json"

# ---------------------------------------------------------------------------
# Known-stale entries in the FROZEN artifact — not tolerated defects.
#
# This file scores a RECORDING. When a recording predates a fix, the recording
# is wrong and the app is right, and the only honest repairs are to re-drive it
# (Task 8 owns that; it needs a live backend) or to hand-edit the JSON — which
# would fabricate a measurement, the exact pathology this repo keeps paying for.
# So the staleness is NAMED here, with its evidence, and made SELF-EXPIRING:
# re-capture the baseline and this test goes red until the entry is deleted.
#
# Scope discipline, because this is the shape a real hole would take:
#   * It excuses ONE (case, invariant) pair — never an invariant, never a case.
#   * It lives in the artifact test ONLY. The checker is untouched, and the LIVE
#     protected suite (tests/acceptance/test_protected_baseline.py) reads the
#     same invariants with NO quarantine — so this bites a real backend at full
#     strength immediately. That is where it was always meant to bite.
#   * An entry that stops failing is an ERROR, not a quiet pass, so it cannot
#     outlive its cause.
# ---------------------------------------------------------------------------
# EMPTY, and that is the mechanism working exactly as designed. The one entry
# this ever held — ("how_to_teach_paragraphing_g3", "cites_own_grade_band") — was
# a recording frozen BEFORE the grade-band retrieval fix (3562f89): the grade-3
# response cited the K-2 book. Task 8's re-drive (baseline-2026-07-17) captured
# the fixed app, the pair went from FAIL to PASS on the new recording, and the
# self-expiry assertion below forced its deletion rather than letting a
# quarantine outlive its cause. Verified across the two recordings before
# removing it:
#   baseline-2026-07-16: FAIL — "Grade 3 (band 3-12) cites the K-2 book"
#   baseline-2026-07-17: PASS — "Grade 3 (band 3-12) cites 3-12"
# Keep this dict empty unless a re-capture genuinely predates a fix again.
_STALE_BASELINE: dict[tuple[str, str], str] = {}


def test_stale_baseline_entries_name_real_cases_and_invariants():
    """A typo'd entry excuses nothing (the real failure still surfaces), but it
    also lingers forever pretending to. Keep the quarantine honest about what it
    refers to."""
    ids = {c.id for c in PROTECTED_SET}
    for case_id, inv in _STALE_BASELINE:
        assert case_id in ids, f"stale-baseline entry names an unknown case: {case_id!r}"
        assert inv in CHECKERS, f"stale-baseline entry names an unknown invariant: {inv!r}"


def test_golden_baseline_satisfies_all_invariants():
    data = json.loads(_BASELINE.read_text())
    by = {c["id"]: c["response"] for c in data}
    failures: list[str] = []
    expired: list[str] = []
    for case in PROTECTED_SET:
        # The wave-boundary re-baseline (baseline-2026-07-14) captured every
        # Protected-Set case, so completeness is enforced hard: a case missing
        # from the recorded JSON means one was added without a re-baseline.
        assert case.id in by, (
            f"Protected case {case.id!r} is missing from the golden baseline — "
            f"re-run scripts/capture_golden_baseline.py."
        )
        for inv, ok, detail in check_all(case, by[case.id]):
            if (case.id, inv) in _STALE_BASELINE:
                if ok:
                    expired.append(f"{case.id}:{inv}")
                continue
            if not ok:
                failures.append(f"{case.id}:{inv} — {detail}")
    assert not failures, "baseline invariant failures:\n" + "\n".join(failures)
    assert not expired, (
        "These entries now PASS — the recording caught up with the app. Delete "
        "them from _STALE_BASELINE; a quarantine that outlives its cause is a "
        "hole in the gate:\n" + "\n".join(expired)
    )
