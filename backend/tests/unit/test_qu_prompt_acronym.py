"""Unit tests for the QU-prompt unknown-subgroup-acronym clause (Fix ③).

These are PROMPT-CONSTRUCTION assertions — no LLM call. They guard against
truncation / accidental deletion of the broadened wording that teaches QU to
flag an unfamiliar acronym naming an intervention block/program/grouping (e.g.
"our WIN block"), not only a bare student label. The real behavioural proof is
the offline-QU gate (campaign/dogfood/probe_win_acronym.py).

Root cause this pins: QU (gpt-5.4-mini) never set unknown_subgroup_acronym for
"WIN block" because the clause framed the trigger as "a short learner label";
"WIN block" reads as an intervention time-block, not a student label.
"""

from __future__ import annotations

from query.qu_v4_prompt import SYSTEM_PROMPT, get_system_prompt


def test_prompt_broadens_acronym_clause_to_intervention_grouping() -> None:
    """The clause must cover an acronym naming which students / what
    intervention block, program, or grouping — not only a bare label."""
    text = get_system_prompt()
    # The broadened scope wording (intervention block / program / grouping).
    assert "intervention block" in text
    assert "program" in text
    assert "grouping" in text
    # Anchored on WHO the lesson is for (keeps strategy acronyms out).
    assert "WHICH STUDENTS" in text


def test_prompt_has_win_positive_example() -> None:
    """A positive WIN example must pin the fire case beside the TAG one."""
    assert 'unknown_subgroup_acronym="WIN"' in SYSTEM_PROMPT
    assert "WIN block" in SYSTEM_PROMPT
    # The original TAG positive must still be present (not clobbered).
    assert 'unknown_subgroup_acronym="TAG"' in SYSTEM_PROMPT


def test_prompt_has_subject_block_negative_example() -> None:
    """A negative example (subject/content time block) must pin the
    boundary so the broadening does not over-fire on 'ELA block'."""
    assert "ELA block" in SYSTEM_PROMPT
    # The negative example must map to null (not fire).
    assert "unknown_subgroup_acronym=null" in SYSTEM_PROMPT
