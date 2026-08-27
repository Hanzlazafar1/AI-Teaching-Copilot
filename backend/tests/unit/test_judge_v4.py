"""Unit tests for judge_v4 — schema + rendering + pass-logic.

The LLM-call behavior is tested in a live acceptance test (Stage 3
acceptance suite). These tests verify the judge's schema, pass/fail
logic, and repair-feedback formatting — all of which are pure.
"""

from __future__ import annotations

import pytest

from generation.lesson import MiniLesson
from validation.judge_v4 import (
    DimensionScore,
    JudgeVerdict,
    _render_lesson_for_judge,
)


# ----------------------------------------------------------------------
# DimensionScore schema
# ----------------------------------------------------------------------


def test_dimension_score_range_enforced() -> None:
    """Score must be in 0..10 (Pydantic validates)."""
    DimensionScore(score=0, violations=[])  # min
    DimensionScore(score=10, violations=[])  # max
    with pytest.raises(Exception):
        DimensionScore(score=-1, violations=[])  # type: ignore[arg-type]
    with pytest.raises(Exception):
        DimensionScore(score=11, violations=[])  # type: ignore[arg-type]


def test_dimension_score_accepts_empty_violations() -> None:
    d = DimensionScore(score=10, violations=[])
    assert d.score == 10
    assert d.violations == []


# ----------------------------------------------------------------------
# JudgeVerdict.passes
# ----------------------------------------------------------------------


def _perfect_score() -> DimensionScore:
    return DimensionScore(score=10, violations=[])


def _failing_score() -> DimensionScore:
    return DimensionScore(score=4, violations=["specific violation"])


def test_verdict_passes_when_all_dimensions_ge_7() -> None:
    verdict = JudgeVerdict(
        narrative_coherence=DimensionScore(score=7, violations=[]),
        strategy_gist_present=DimensionScore(score=8, violations=[]),
        step1_structure=DimensionScore(score=9, violations=[]),
    )
    assert verdict.passes is True


def test_verdict_fails_when_any_dimension_below_7() -> None:
    # narrative failing
    v = JudgeVerdict(
        narrative_coherence=_failing_score(),
        strategy_gist_present=_perfect_score(),
        step1_structure=_perfect_score(),
    )
    assert v.passes is False

    # strategy-gist failing
    v = JudgeVerdict(
        narrative_coherence=_perfect_score(),
        strategy_gist_present=_failing_score(),
        step1_structure=_perfect_score(),
    )
    assert v.passes is False

    # step1 failing
    v = JudgeVerdict(
        narrative_coherence=_perfect_score(),
        strategy_gist_present=_perfect_score(),
        step1_structure=_failing_score(),
    )
    assert v.passes is False


def test_verdict_boundary_score_6_fails_7_passes() -> None:
    """Pass threshold is 7 — score=6 fails, score=7 passes."""
    v6 = JudgeVerdict(
        narrative_coherence=DimensionScore(score=6, violations=["borderline"]),
        strategy_gist_present=_perfect_score(),
        step1_structure=_perfect_score(),
    )
    assert v6.passes is False

    v7 = JudgeVerdict(
        narrative_coherence=DimensionScore(score=7, violations=[]),
        strategy_gist_present=_perfect_score(),
        step1_structure=_perfect_score(),
    )
    assert v7.passes is True


# ----------------------------------------------------------------------
# repair_feedback — the string that drives retry prompts
# ----------------------------------------------------------------------


def test_repair_feedback_empty_when_passing() -> None:
    v = JudgeVerdict(
        narrative_coherence=_perfect_score(),
        strategy_gist_present=_perfect_score(),
        step1_structure=_perfect_score(),
    )
    assert v.repair_feedback() == ""


def test_repair_feedback_lists_specific_violations() -> None:
    v = JudgeVerdict(
        narrative_coherence=DimensionScore(
            score=4,
            violations=["'listy' appears in Step 4 but was not introduced earlier"],
        ),
        strategy_gist_present=_perfect_score(),
        step1_structure=DimensionScore(
            score=5, violations=["missing: trait_connection", "missing: purpose"]
        ),
    )
    feedback = v.repair_feedback()

    # Failed dimensions are named; passing ones are omitted
    assert "NARRATIVE COHERENCE" in feedback
    assert "STEP 1 STRUCTURE" in feedback
    assert "NAMED-STRATEGY GIST" not in feedback

    # Scores cited for context
    assert "4/10" in feedback
    assert "5/10" in feedback

    # Specific violations verbatim
    assert "'listy' appears in Step 4" in feedback
    assert "missing: trait_connection" in feedback
    assert "missing: purpose" in feedback


# ----------------------------------------------------------------------
# _render_lesson_for_judge
# ----------------------------------------------------------------------


def _sample_lesson() -> MiniLesson:
    return MiniLesson(
        skill_focus="topic sentences",
        grade_level="3",
        writing_mode="Inform",
        step_1_introduce="Today we're going to learn about topic sentences.",
        step_2a_tell="A topic sentence is the main idea of a paragraph.",
        step_2b_show="Let me model this. I close my eyes and think...",
        step_3_interact="Help me with the next one. Turn and talk...",
        step_4_close="Great work today! For independent writing...",
    )


def test_render_lesson_labels_each_step() -> None:
    text = _render_lesson_for_judge(_sample_lesson())
    assert "SKILL: topic sentences" in text
    assert "GRADE: 3" in text
    assert "MODE: Inform" in text
    assert "STEP 1 INTRODUCE" in text
    assert "STEP 2A TELL" in text
    assert "STEP 2B SHOW" in text
    assert "STEP 3 INTERACT" in text
    assert "STEP 4 CLOSE" in text


def test_render_lesson_preserves_step_content_verbatim() -> None:
    lesson = _sample_lesson()
    text = _render_lesson_for_judge(lesson)
    assert lesson.step_1_introduce in text
    assert lesson.step_2b_show in text
    assert lesson.step_4_close in text
