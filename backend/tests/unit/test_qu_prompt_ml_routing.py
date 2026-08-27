"""Unit tests for the QU-prompt BARE mini-lesson request clause (routing fix (i)).

These are PROMPT-CONSTRUCTION assertions — no LLM call. They guard against
truncation / accidental deletion of the rule that teaches QU to route a bare
"give me a mini lesson" (NO skill named) to SCRIPTED_ML, so the app ASKS which
grade/skill instead of drifting to COACHING (which invents a skill and answers
in prose) or META. The behavioural proof is the offline-QU ship-gate
(campaign/dogfood/probe_ml_routing.py: positives 30/30 SCRIPTED_ML, lookups
0/18 regressions).

Root cause this pins: SCRIPTED_ML rule 4's trigger phrases all NAME a skill, and
"mini-lesson" is listed as a NEVER-SKILL technique term — so a bare lesson
request matched no clean rule and was occasionally grabbed by COACHING (rule 9,
the terse-follow-up catch-all) or META (rule 3). The classification is a
knife's edge, so this nudge hardens the INITIAL request; the deterministic
clarify-resume rule is what guarantees the FOLLOW-UP half.
"""

from __future__ import annotations

from query.qu_v4_prompt import SYSTEM_PROMPT, get_system_prompt


def test_prompt_routes_bare_mini_lesson_request_to_scripted_ml() -> None:
    """A bare lesson request (no skill named) must be taught as SCRIPTED_ML."""
    text = get_system_prompt()
    assert "give me a mini lesson" in text
    # It must say BOTH fields are then missing, so the app asks which.
    assert '"grade" and "skill" in missing_required' in text


def test_prompt_forbids_routing_bare_request_to_coaching_or_meta() -> None:
    """The explicit negative: not COACHING (rule 9) / META (rule 3) merely
    because no skill is named. Kills a reworded clause that drops the ban."""
    text = get_system_prompt()
    assert "Do NOT send these to COACHING" in text
    assert "META" in text


def test_prompt_keeps_the_lookup_exclusion() -> None:
    """The load-bearing guard: a LOOKUP ("is there a lesson with X?") must
    still route to COACHING — the nudge must not swallow lookups into
    SCRIPTED_ML. Kills an over-broadening that deletes the exclusion."""
    assert "is there a lesson with X?" in SYSTEM_PROMPT
    assert "lookup/coaching questions" in SYSTEM_PROMPT
