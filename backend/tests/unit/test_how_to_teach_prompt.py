"""Prompt-content + threading tests for the HOW_TO_TEACH handler.

Brady Fm5: HOW_TO_TEACH must NOT author its own book/page citation — it POINTS
at the block each claim came from (`[[src:<chunk_id>]]`) and the deterministic
citation is built for it downstream (handlers.citation.resolve_markers, applied
at _base_text._build_text_outcome). These tests lock the prompt's citation
discipline so the rules stay in sync with that redesign.

Brady SG2 (57:30) + SG3 (58:40): when a developmental writing level is present
(subgroup / early writer), the outline frames each sub-skill AT that stage and
RESTATES the stage in every bulleted skill. These tests lock the shared rule
fragment's content and its deterministic threading into the built prompt (no
LLM — pure prompt construction).
"""

from __future__ import annotations

from handlers._prompt_rules import (
    EARLY_WRITER_STAGE_PER_BULLET_RULE,
    EARLY_WRITER_STAGE_RULE,
)
from handlers.how_to_teach import _HOW_TO_TEACH_RULES, _build_prompt
from schemas import Conversation, RequestType, SkillSpec, TurnIntent


def _build(intent: TurnIntent) -> str:
    return _build_prompt(intent, "", Conversation(session_id="s"), None)


def _htt_intent(**kw) -> TurnIntent:
    return TurnIntent(request_type=RequestType.HOW_TO_TEACH, **kw)


def test_how_to_teach_prompt_defers_citation_to_python():
    assert "MAY cite" not in _HOW_TO_TEACH_RULES
    assert "added for you" in _HOW_TO_TEACH_RULES


def test_writing_level_threads_into_how_to_teach_prompt():
    """SG2 threading (deterministic, no LLM): when writing_level is set it
    reaches the generation prompt — the stage value appears in SESSION CONTEXT
    and the early-writer stage rule is spliced in."""
    prompt = _build(_htt_intent(
        skill=SkillSpec(canonical="leads", as_stated="strong leads"),
        writing_level="label",
    ))
    assert "label" in prompt                     # the stage value threaded
    assert EARLY_WRITER_STAGE_RULE in prompt      # the SG2/SG3 rule spliced in


def test_no_writing_level_is_noop_in_how_to_teach_prompt():
    """No-op when there's no writing level (not a subgroup / early-writer turn):
    the stage rule must NOT be injected, so normal outlines are unchanged."""
    prompt = _build(_htt_intent(
        skill=SkillSpec(canonical="leads", as_stated="strong leads"),
    ))
    assert EARLY_WRITER_STAGE_RULE not in prompt


def test_stage_rule_repeats_stage_per_bullet():
    """SG3 (Brady 58:40): the BUILT outline prompt must instruct RESTATING the
    stage in EACH bulleted skill (repeat per bullet, not state-once) and name
    the four developmental stages so the model frames skills concretely.

    Asserted against the built prompt rather than the rule constant: SG2's core
    is now shared with the SCRIPTED_ML builder while SG3's per-bullet clause
    stays outline-only, so what matters is that BOTH still reach THIS prompt.
    (The old constant-only assertion could not catch a builder that stopped
    splicing the per-bullet clause.)
    """
    prompt = _build(_htt_intent(
        skill=SkillSpec(canonical="leads", as_stated="strong leads"),
        writing_level="label",
    ))
    lowered = prompt.lower()
    assert "each" in lowered
    assert "bullet" in lowered
    assert "repeat" in lowered
    for stage in ("picture", "label", "word", "sentence"):
        assert stage in lowered


def test_per_bullet_rule_is_outline_only():
    """SG3's restate-per-bullet clause belongs to the bulleted outline ONLY —
    it must not migrate into the shared SG2 core, or the SCRIPTED_ML 4-step
    lesson (which has no bulleted skill list) would inherit it."""
    assert "bullet" in EARLY_WRITER_STAGE_PER_BULLET_RULE.lower()
    assert "bullet" not in EARLY_WRITER_STAGE_RULE.lower()


def test_stage_rule_frames_skill_at_stage():
    """SG2 (Brady 57:30): the rule frames the grade-level skill AT the
    developmental stage rather than the on-grade written form."""
    lowered = EARLY_WRITER_STAGE_RULE.lower()
    assert "stage" in lowered
    assert "grade" in lowered
