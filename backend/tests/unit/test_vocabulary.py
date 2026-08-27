"""Tests for validation/vocabulary.py (Wave 0 Part 2 test colocation)."""
from __future__ import annotations

from validation.vocabulary import (
    validate_details_not_reasons,
    validate_skill_focus_vocab,
    validate_story_only_narrative,
    validate_trigger_usage,
)
from tests.unit._policy_fixtures import _good_lesson


class TestSkillFocusVocab:
    def test_matching_phrase_passes(self):
        l = _good_lesson(skill_focus="topic sentence and supporting details")
        assert validate_skill_focus_vocab(l, "topic sentence and supporting details") == []

    def test_case_insensitive(self):
        l = _good_lesson(skill_focus="Topic Sentence and Supporting Details")
        assert validate_skill_focus_vocab(l, "topic sentence and supporting details") == []

    def test_missing_phrase_flagged(self):
        l = _good_lesson(skill_focus="table-top-leg paragraphing")
        errors = validate_skill_focus_vocab(l, "topic sentence and supporting details")
        assert errors
        assert "topic sentence" in errors[0]

    def test_empty_user_phrase_no_check(self):
        l = _good_lesson(skill_focus="whatever")
        assert validate_skill_focus_vocab(l, "") == []


class TestTriggerUsage:
    def test_trigger_present_passes(self):
        text = "Use the pizza-table strategy to organize paragraphs."
        assert validate_trigger_usage(text, ["pizza-table"]) == []

    def test_natural_language_form_accepted(self):
        text = "Use the pizza table strategy to organize paragraphs."
        assert validate_trigger_usage(text, ["pizza-table"]) == []

    def test_missing_trigger_flagged(self):
        text = "Students organize their paragraphs with a graphic organizer."
        errors = validate_trigger_usage(text, ["pizza-table"])
        assert errors
        assert "pizza-table" in errors[0]

    def test_no_triggers_given_no_check(self):
        assert validate_trigger_usage("any text", []) == []


class TestDetailsNotReasons:
    """Brady N1: K-1 opinion/persuasive must say 'details', never 'reasons'.
    Grades 2-12 (and non-persuasive modes) are handled by the prompt, so the
    validator stays silent there — it only fires on the K-1 persuasive case."""

    # --- brief's four canonical cases ---
    def test_k1_persuasive_reasons_flagged(self):
        errors = validate_details_not_reasons(
            "List your reasons why.", grade="1", mode="Persuade"
        )
        assert errors
        assert "details" in errors[0].lower()

    def test_k1_persuasive_details_clean(self):
        assert (
            validate_details_not_reasons(
                "List your details why.", grade="K", mode="Persuade"
            )
            == []
        )

    def test_grade4_persuasive_reasons_not_flagged(self):
        assert (
            validate_details_not_reasons(
                "Give three reasons.", grade="4", mode="Persuade"
            )
            == []
        )

    def test_inform_reasons_not_flagged(self):
        assert (
            validate_details_not_reasons(
                "List your reasons.", grade="1", mode="Inform"
            )
            == []
        )

    # --- edge cases (production-grade coverage) ---
    def test_kindergarten_persuasive_reasons_flagged(self):
        # "K" band is covered alongside "1".
        assert validate_details_not_reasons(
            "Tell me your reasons.", grade="K", mode="Persuade"
        )

    def test_singular_reason_flagged(self):
        # Regex is r"\breasons?\b" — the singular form counts too.
        assert validate_details_not_reasons(
            "Give one good reason.", grade="1", mode="Persuade"
        )

    def test_case_insensitive(self):
        assert validate_details_not_reasons(
            "Reasons matter here.", grade="1", mode="Persuade"
        )

    def test_whole_word_only_reasonable_not_flagged(self):
        # 'reasonable' embeds 'reason' but is a different word — must not flag.
        assert (
            validate_details_not_reasons(
                "Be reasonable about it.", grade="1", mode="Persuade"
            )
            == []
        )

    def test_none_grade_no_flag(self):
        assert (
            validate_details_not_reasons(
                "List your reasons.", grade=None, mode="Persuade"
            )
            == []
        )

    def test_none_mode_no_flag(self):
        assert (
            validate_details_not_reasons(
                "List your reasons.", grade="1", mode=None
            )
            == []
        )

    def test_empty_text_no_flag(self):
        assert (
            validate_details_not_reasons("", grade="1", mode="Persuade") == []
        )

    def test_none_text_no_flag(self):
        assert (
            validate_details_not_reasons(None, grade="1", mode="Persuade") == []
        )


class TestStoryOnlyNarrative:
    """Brady N2: 'story'/'storytelling'/'stories' is narrative-only (Entertain).
    In Inform/Persuade writing the response must steer to 'your writing piece' /
    'your informative|persuasive piece'. None and 'all' keep the rule inert."""

    # --- brief's canonical cases ---
    def test_inform_story_flagged(self):
        errors = validate_story_only_narrative("Write a story.", mode="Inform")
        assert errors
        assert "story" in errors[0].lower()
        assert "informative" in errors[0].lower()

    def test_persuade_storytelling_flagged(self):
        errors = validate_story_only_narrative(
            "Use storytelling to hook the reader.", mode="Persuade"
        )
        assert errors
        assert "persuasive" in errors[0].lower()

    def test_entertain_story_clean(self):
        assert (
            validate_story_only_narrative("Write a story.", mode="Entertain") == []
        )

    def test_none_mode_clean(self):
        assert validate_story_only_narrative("Write a story.", mode=None) == []

    def test_all_mode_clean(self):
        assert validate_story_only_narrative("Write a story.", mode="all") == []

    # --- whole-word coverage (regex r"\bstor(?:y|ytelling|ies)\b") ---
    def test_stories_plural_flagged(self):
        # The plural alternation 'ies' counts.
        assert validate_story_only_narrative(
            "Students share their stories.", mode="Inform"
        )

    def test_storyline_not_flagged(self):
        # 'storyline' embeds 'story' but is a different word — no word boundary.
        assert (
            validate_story_only_narrative("Explain the storyline.", mode="Inform")
            == []
        )

    def test_history_not_flagged(self):
        # 'history' contains 'stor' mid-word — not preceded by a boundary.
        assert (
            validate_story_only_narrative("Teach the history unit.", mode="Inform")
            == []
        )

    def test_case_insensitive(self):
        assert validate_story_only_narrative("A STORY goes here.", mode="Persuade")

    def test_empty_text_no_flag(self):
        assert validate_story_only_narrative("", mode="Inform") == []

    def test_none_text_no_flag(self):
        assert validate_story_only_narrative(None, mode="Inform") == []
