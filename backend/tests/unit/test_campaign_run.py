"""Unit tests for the campaign drive+judge controller (``campaign/run.py``).

The controller plans N re-probes per claim/scenario, drives each through a
fresh session, judges it, and appends to a resumable JSONL — with a hard cost
kill-switch. These tests pin that contract fully mocked: no live backend, no
OpenAI, no real network.
"""
from __future__ import annotations

import pytest

from campaign import drive, run
from campaign.judge import Verdict

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# #56 — the drive must hand the judge the EXCHANGE for a multi-turn probe.
# `_default_drive_fn` returned only the last envelope, so a rubric about a FLOW
# ("asks first, then delivers") was judged on the delivery alone and read as an
# assumption. Proven live on the u3 re-drive: MISALIGNED @0.95 on the last turn,
# ALIGNED @0.9 once Turn 1 was visible.
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stands in for drive.Session: one envelope per send, recording order."""

    def __init__(self, base_url, cache_path=None):
        self.sent: list[str] = []

    def send(self, message, model="gpt-4o"):
        self.sent.append(message)
        return drive.Envelope(raw={"response": f"reply-to::{message}"}, status="OK",
                              turn_idx=len(self.sent) - 1)


def test_default_drive_attaches_prior_turns_for_a_multi_turn_probe(monkeypatch):
    monkeypatch.setattr(run.drive, "Session", _FakeSession)
    env = run._default_drive_fn()("http://x", ["first", "second"], "gpt-5.4", "COACHING")
    # The judged envelope is still the FINAL turn...
    assert env.get("response") == "reply-to::second"
    # ...now carrying the earlier exchange so a flow rubric is decidable.
    assert env.get("prior_turns") == [
        {"message": "first", "response": "reply-to::first"},
    ]


def test_default_drive_single_turn_carries_no_prior_turns(monkeypatch):
    # BACK-COMPAT: the overwhelming majority of probes are single-turn and must
    # reach the judge exactly as before (no new key, no prompt drift).
    monkeypatch.setattr(run.drive, "Session", _FakeSession)
    env = run._default_drive_fn()("http://x", ["only"], "gpt-5.4", "COACHING")
    assert env.get("response") == "reply-to::only"
    assert env.get("prior_turns") is None


def test_default_drive_does_not_mutate_the_cached_envelope(monkeypatch):
    # prior_turns is judge-facing metadata. It must not be written back into the
    # per-turn envelope the Session already cached to drive-cache.jsonl, or the
    # cache stops being a faithful record of what the backend actually returned.
    captured: list = []

    class _Recording(_FakeSession):
        def send(self, message, model="gpt-4o"):
            env = super().send(message, model=model)
            captured.append(env)
            return env

    monkeypatch.setattr(run.drive, "Session", _Recording)
    run._default_drive_fn()("http://x", ["first", "second"], "gpt-5.4", "COACHING")
    assert "prior_turns" not in captured[0].raw
    assert "prior_turns" not in captured[-1].raw


MANIFEST = {
    "N": {"safety-non-negotiable": 10, "non-negotiable": 10, "important": 5, "minor": 5},
    "drive_model": "gpt-5.4",
    "concurrency": {"max_parallel_sessions": 4},
}

CLAIMS = [
    {
        "id": "c-safety", "tier": "safety-non-negotiable", "surface": "COACHING",
        "judge_method": "deterministic", "observable": "validate_no_forbidden_words",
        "scenarios": [{"tier": "representative", "turns": ["one"], "expected": "x"}],
    },
    {
        "id": "c-imp", "tier": "important", "surface": "META",
        "judge_method": "llm-judge", "observable": "response-content",
        "scenarios": [
            {"tier": "representative", "turns": ["a"], "expected": "y"},
            {"tier": "multi-turn", "turns": ["b1", "b2"], "expected": "z"},
        ],
    },
]


def _env_ok():
    return drive.Envelope(raw={"response": "clean answer"}, status="OK")


def _env_nonverdict():
    return drive.Envelope(raw={}, status="NON_VERDICT", http_status=503)


def _aligned(claim, env):
    return Verdict("ALIGNED", 1.0, "ok", claim.get("judge_method", ""), "")


# ---------------------------------------------------------------------------
# plan_probes — N per tier, scenarios expanded, multi-turn preserved
# ---------------------------------------------------------------------------


def test_plan_probes_n_per_tier():
    probes = run.plan_probes(CLAIMS, MANIFEST)
    # c-safety: 1 scenario x N=10; c-imp: 2 scenarios x N=5 = 10
    assert len([p for p in probes if p.claim_id == "c-safety"]) == 10
    assert len([p for p in probes if p.claim_id == "c-imp"]) == 10
    assert len(probes) == 20
    # the multi-turn scenario carries both literal turns
    mt = [p for p in probes if p.claim_id == "c-imp" and p.scenario_idx == 1][0]
    assert mt.turns == ["b1", "b2"]
    assert mt.tier == "important"


def test_plan_probes_unknown_tier_defaults_to_five():
    claims = [{"id": "c", "tier": "weird", "surface": "X",
               "scenarios": [{"turns": ["t"], "expected": "e"}]}]
    assert len(run.plan_probes(claims, MANIFEST)) == 5


# ---------------------------------------------------------------------------
# run_campaign — one result line per probe, resumable
# ---------------------------------------------------------------------------


def test_run_campaign_writes_one_line_per_probe_and_is_resumable(tmp_path):
    results = tmp_path / "results.jsonl"
    drives: list = []

    def drive_fn(base_url, turns, model, surface):
        drives.append(turns)
        return _env_ok()

    run.run_campaign(CLAIMS, MANIFEST, "http://x", str(results),
                     drive_fn=drive_fn, judge_fn=_aligned)

    lines = results.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 20
    assert len(drives) == 20

    # resume: everything already ALIGNED (ok=True) -> zero new drives
    drives.clear()
    run.run_campaign(CLAIMS, MANIFEST, "http://x", str(results),
                     drive_fn=drive_fn, judge_fn=_aligned)
    assert len(drives) == 0
    assert len(results.read_text(encoding="utf-8").strip().splitlines()) == 20


def test_result_record_shape(tmp_path):
    results = tmp_path / "r.jsonl"
    run.run_campaign([CLAIMS[0]], MANIFEST, "http://x", str(results),
                     drive_fn=lambda *a: _env_ok(), judge_fn=_aligned)
    import json
    rec = json.loads(results.read_text(encoding="utf-8").strip().splitlines()[0])
    for k in ("claim_id", "scenario_idx", "probe_idx", "tier", "surface",
              "status", "confidence", "ok"):
        assert k in rec
    assert rec["status"] == "ALIGNED"
    assert rec["ok"] is True


# ---------------------------------------------------------------------------
# Kill-switch — a meter already over cap schedules ZERO drives
# ---------------------------------------------------------------------------


def test_kill_switch_pre_over_budget_schedules_zero_drives(tmp_path):
    results = tmp_path / "r.jsonl"
    drives: list = []
    meter = run.CostMeter(dollar_cap=1.0, per_turn_cost={"default": 0.10})
    meter._spent = 5.0  # pre-loaded past the cap

    run.run_campaign(CLAIMS, MANIFEST, "http://x", str(results),
                     drive_fn=lambda *a: drives.append(a) or _env_ok(),
                     judge_fn=_aligned, budget=meter)
    assert len(drives) == 0


def test_cost_meter_charges_and_trips():
    m = run.CostMeter(dollar_cap=0.25, per_turn_cost={"SCRIPTED_ML": 0.10, "default": 0.02})
    assert not m.over_cap()
    m.charge("SCRIPTED_ML", turns=1)   # 0.10
    m.charge("SCRIPTED_ML", turns=1)   # 0.20
    assert not m.over_cap()
    m.charge("SCRIPTED_ML", turns=1)   # 0.30 -> over
    assert m.over_cap()
    assert m.calls == 3


# ---------------------------------------------------------------------------
# NON_VERDICT — recorded, but re-driven on resume (never silently "done")
# ---------------------------------------------------------------------------


def test_non_verdict_is_recorded_but_retried_on_resume(tmp_path):
    results = tmp_path / "r.jsonl"

    # First pass: every drive is a NON_VERDICT (upstream error).
    run.run_campaign(CLAIMS, MANIFEST, "http://x", str(results),
                     drive_fn=lambda *a: _env_nonverdict(),
                     judge_fn=lambda c, e: Verdict("UNCERTAIN", 0.0, "non-verdict", "", ""))
    assert len(results.read_text(encoding="utf-8").strip().splitlines()) == 20

    # Resume with a healthy backend: because those were ok=False, ALL re-drive.
    drives: list = []
    run.run_campaign(CLAIMS, MANIFEST, "http://x", str(results),
                     drive_fn=lambda *a: drives.append(a) or _env_ok(),
                     judge_fn=_aligned)
    assert len(drives) == 20
