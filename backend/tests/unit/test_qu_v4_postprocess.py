"""Unit tests for QU v4 post-processing logic (no LLM call).

The post-processor is a pure function that takes whatever the LLM
returned and applies canonicalization + safety nets. Tests exercise
the Turn-5-style edge cases explicitly so regressions are loud.
"""

from __future__ import annotations

import pytest

from query.qu_v4 import _postprocess
from canonicalizer import get_canonicalizer
from schemas import (
    GradeSpec,
    RequestType,
    SkillSpec,
    TurnIntent,
)


@pytest.fixture(scope="module")
def canon():
    return get_canonicalizer()


# ----------------------------------------------------------------------
# Skill canonicalization safety net
# ----------------------------------------------------------------------


def test_postprocess_canonicalizes_skill_synonym(canon) -> None:
    """LLM emits 'topic sentence' (singular); post-processor normalizes
    to 'topic sentences' (canonical)."""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(
            canonical="topic sentence",  # ← non-canonical
            as_stated="topic sentence and supporting details",
        ),
    )
    fixed = _postprocess(intent, canon)
    assert fixed.skill is not None
    assert fixed.skill.canonical == "topic sentences"
    # as_stated must survive — teacher vocab preserved
    assert fixed.skill.as_stated == "topic sentence and supporting details"


def test_postprocess_resolves_trigger_synonym(canon) -> None:
    """LLM emits 'tables and legs' as skill.canonical; post-processor
    resolves to Smekens canonical 'pizza-table'."""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(
            canonical="tables and legs",
            as_stated="tables and legs",
        ),
    )
    fixed = _postprocess(intent, canon)
    assert fixed.skill.canonical == "pizza-table"


def test_postprocess_passes_already_canonical_skill_through(canon) -> None:
    """When LLM emits a canonical form already, no mutation happens."""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(
            canonical="transitions",
            as_stated="transitions",
        ),
    )
    fixed = _postprocess(intent, canon)
    assert fixed.skill.canonical == "transitions"


# ----------------------------------------------------------------------
# META-TECHNIQUE guard (the Turn 5 fix at the post-processor level)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "meta_term",
    ["think-aloud", "think aloud", "mini-lesson",
     "turn-and-talk", "gradual release", "explicit instruction"],
)
def test_postprocess_nulls_meta_technique_skill(canon, meta_term: str) -> None:
    """If the LLM emits a meta-technique as skill.canonical despite the
    prompt rule, the post-processor strips it. Downstream code must
    inherit skill from prior turn instead."""
    intent = TurnIntent(
        request_type=RequestType.DEEPEN_PRIOR,
        skill=SkillSpec(
            canonical=meta_term,
            as_stated=meta_term,
        ),
    )
    fixed = _postprocess(intent, canon)
    # skill is nulled; downstream must recover from conversation
    assert fixed.skill is None


def test_postprocess_preserves_real_skill_even_with_technique_in_as_stated(canon) -> None:
    """If the LLM correctly extracted a real skill even though the
    user mentioned a meta-technique in their query, the skill survives.
    The meta-technique guard only fires when canonical IS a technique."""
    intent = TurnIntent(
        request_type=RequestType.DEEPEN_PRIOR,
        skill=SkillSpec(
            canonical="topic sentences",         # ← real skill
            as_stated="deepen the think-aloud",  # ← phrasing contains technique
        ),
    )
    fixed = _postprocess(intent, canon)
    assert fixed.skill is not None
    assert fixed.skill.canonical == "topic sentences"


# ----------------------------------------------------------------------
# required_triggers canonicalization
# ----------------------------------------------------------------------


def test_postprocess_canonicalizes_triggers(canon) -> None:
    """Trigger synonyms resolve to canonical. Unknown triggers dropped."""
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        required_triggers=[
            "pizza table",            # synonym for pizza-table
            "slinky test",            # synonym for slinky-test
            "totally made-up term",   # should be dropped
        ],
    )
    fixed = _postprocess(intent, canon)
    assert "pizza-table" in fixed.required_triggers
    assert "slinky-test" in fixed.required_triggers
    assert "totally made-up term" not in fixed.required_triggers


def test_postprocess_keeps_empty_triggers_list(canon) -> None:
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        required_triggers=[],
    )
    fixed = _postprocess(intent, canon)
    assert fixed.required_triggers == []


# ----------------------------------------------------------------------
# No-op cases
# ----------------------------------------------------------------------


def test_postprocess_intent_without_skill_or_triggers(canon) -> None:
    """META intents have no skill/triggers — post-processor passes
    through unchanged."""
    intent = TurnIntent(request_type=RequestType.META)
    fixed = _postprocess(intent, canon)
    assert fixed == intent


def test_postprocess_preserves_all_other_fields(canon) -> None:
    """Canonicalization must not disturb grade/mode/trait/continuity/
    confirmation/clarification fields."""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="3", stated_explicit=True, stated_turn=0),
        skill=SkillSpec(canonical="topic sentence", as_stated="topic sentences"),
        refers_to_prior=True,
        prior_turn_ref=2,
        needs_confirmation=True,
        confirmation_reason="ambiguous grade",
        missing_required=["mode"],
    )
    fixed = _postprocess(intent, canon)
    # These must all survive verbatim
    assert fixed.grade.value == "3"
    assert fixed.grade.stated_turn == 0
    assert fixed.refers_to_prior is True
    assert fixed.prior_turn_ref == 2
    assert fixed.needs_confirmation is True
    assert fixed.confirmation_reason == "ambiguous grade"
    assert fixed.missing_required == ["mode"]
    # Only canonical was adjusted
    assert fixed.skill.canonical == "topic sentences"
