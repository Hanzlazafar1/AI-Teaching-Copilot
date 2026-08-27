"""Unit tests for the composite policy validators (validation/policy.py).

Per-validator tests live in test_forbidden_words / test_endings / test_citations /
test_vocabulary / test_structure (Wave 0 Part 2 colocation). This file keeps the
two composite orchestrators.
"""
from __future__ import annotations

from validation.policy import (
    LessonPolicyResult,
    validate_lesson_policy,
    validate_markdown_response,
)
from tests.unit._policy_fixtures import _good_lesson


class TestLessonPolicyComposite:
    def test_good_lesson_passes_all_rules(self):
        l = _good_lesson()
        result = validate_lesson_policy(
            l,
            retrieved_context="",  # no Launch chunk → no citation rule
            response_text=f"{l.step_1_introduce}\n{l.step_2a_tell}\n{l.step_2b_show}\n{l.step_3_interact}\n{l.step_4_close}",
            user_skill_phrase="transitions between paragraphs",
            triggered_trigger_names=None,
        )
        assert result.passed, result.errors

    def test_forbidden_word_aggregated(self):
        l = _good_lesson(step_1_introduce="Today we discuss writing.")
        result = validate_lesson_policy(
            l,
            retrieved_context="",
            response_text=f"{l.step_1_introduce}\n{l.step_2a_tell}",
            user_skill_phrase="",
        )
        assert not result.passed
        assert any("discuss" in e.lower() for e in result.errors)

    def test_feedback_block_format(self):
        result = LessonPolicyResult(errors=["Rule A violated.", "Rule B violated."])
        block = result.as_feedback_block()
        assert "Rule A violated" in block
        assert "Rule B violated" in block
        assert block.startswith("Your previous lesson violated")

    def test_n1_reasons_flagged_for_k1_persuasive(self):
        # grade/mode threaded through → K-1 persuasive "reasons" is caught.
        # The lesson must be coherent with the grade it's validated under:
        # grade="1" is the K-2 band, so its close must be the K-2 phrase —
        # otherwise the (now-wired) E1 check would append a spurious
        # grade-band error that the loose N1 assertion would silently mask.
        l = _good_lesson(
            grade_level="1",
            step_4_close="Today you practiced. Let's go be writers!",
        )
        result = validate_lesson_policy(
            l,
            retrieved_context="",
            response_text="Now list your reasons why you feel that way.",
            grade="1",
            mode="Persuade",
        )
        assert any("Brady N1" in e for e in result.errors), result.errors

    def test_n1_not_flagged_for_grade4_persuasive(self):
        # Same text + mode, higher grade → the rule stays silent (grade is
        # honored, not ignored), proving the param actually threads through.
        l = _good_lesson()
        result = validate_lesson_policy(
            l,
            retrieved_context="",
            response_text="Now list your reasons why you feel that way.",
            grade="4",
            mode="Persuade",
        )
        assert not any("Brady N1" in e for e in result.errors), result.errors

    def test_n1_inert_when_grade_mode_defaulted(self):
        # Caller omits grade/mode (defaults None) → rule never fires, so the
        # new param can't retroactively break existing call sites.
        l = _good_lesson()
        result = validate_lesson_policy(
            l,
            retrieved_context="",
            response_text="Now list your reasons why you feel that way.",
        )
        assert not any("Brady N1" in e for e in result.errors), result.errors

    def test_n2_story_flagged_for_informative(self):
        # mode threaded through → "story" in non-narrative writing is caught.
        l = _good_lesson()
        result = validate_lesson_policy(
            l,
            retrieved_context="",
            response_text="Have students write a story about their topic.",
            mode="Inform",
        )
        assert any("Brady N2" in e for e in result.errors), result.errors

    def test_n2_not_flagged_for_narrative(self):
        # Same text under Entertain (narrative) → the rule stays silent.
        l = _good_lesson()
        result = validate_lesson_policy(
            l,
            retrieved_context="",
            response_text="Have students write a story about their topic.",
            mode="Entertain",
        )
        assert not any("Brady N2" in e for e in result.errors), result.errors

    def test_n2_inert_when_mode_defaulted(self):
        # Caller omits mode (defaults None) → rule never fires.
        l = _good_lesson()
        result = validate_lesson_policy(
            l,
            retrieved_context="",
            response_text="Have students write a story about their topic.",
        )
        assert not any("Brady N2" in e for e in result.errors), result.errors


class TestMarkdownResponseValidator:
    def test_good_how_to_teach_passes(self):
        resp = (
            "Use the pizza-table strategy for paragraphing.\n\n"
            "1. Introduce the topic\n2. Add a supporting detail\n"
            "3. Add another supporting detail\n\n"
            "This is covered in Launching the Writers Workshop 3-12 on page 64. "
            "You can also find the graphic organizer in the book's digital resources.\n\n"
            "Are you ready for a scripted mini-lesson on this skill?"
        )
        ctx = "Source: lww312-s8-ml05-table-top | Book: Launching the Writers Workshop 3-12 | Page: 64"
        errors = validate_markdown_response(
            query_type="HOW_TO_TEACH",
            response_text=resp,
            retrieved_context=ctx,
            triggered_trigger_names=["pizza-table"],
        )
        assert errors == [], errors

    def test_missing_ending_aggregated(self):
        resp = "Body text about paragraphing."
        errors = validate_markdown_response(
            query_type="HOW_TO_TEACH",
            response_text=resp,
            retrieved_context="",
        )
        assert any("ready for a scripted mini-lesson" in e.lower() for e in errors)


class TestMarkdownResponseVocabulary:
    """Brady N1/N2 now enforced on the markdown path, gated by grade+mode
    exactly as validate_lesson_policy gates them for SCRIPTED_ML."""

    def _md(self, text, grade=None, mode=None):
        return validate_markdown_response(
            query_type="COACHING_GENERAL", response_text=text,
            retrieved_context="", grade=grade, mode=mode)

    def test_n2_story_flagged_informative(self):
        assert any("N2" in e for e in self._md("Have them tell a story about the facts.", mode="Inform"))

    def test_n2_story_flagged_persuasive_uses_persuasive_piece(self):
        errors = self._md("Have them tell a story.", mode="Persuade")
        assert any("N2" in e for e in errors)
        assert any("persuasive piece" in e for e in errors)

    def test_n2_story_ok_narrative(self):
        assert not any("N2" in e for e in self._md("Have them tell a story.", mode="Entertain"))

    def test_n2_inert_mode_all(self):
        assert not any("N2" in e for e in self._md("Tell a story.", mode="all"))

    def test_n1_reasons_flagged_k_persuasive(self):
        assert any("N1" in e for e in self._md("Give three reasons.", grade="K", mode="Persuade"))

    def test_n1_reasons_flagged_grade1_persuasive(self):
        assert any("N1" in e for e in self._md("Give three reasons.", grade="1", mode="Persuade"))

    def test_n1_reasons_ok_grade3(self):
        assert not any("N1" in e for e in self._md("Give three reasons.", grade="3", mode="Persuade"))

    def test_backward_compatible_without_grade_mode(self):
        assert not any(("N1" in e or "N2" in e) for e in self._md("Tell a story with reasons."))
