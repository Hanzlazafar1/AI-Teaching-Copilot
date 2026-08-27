"""Tests for validation/structure.py (Wave 0 Part 2 test colocation)."""
from __future__ import annotations

from validation.structure import (
    STEP_2A_MIN_MULTIPLIER,
    STEP_2B_MIN_MULTIPLIER,
    STEP_3_REQUIRED_PHRASES,
    validate_lesson_depth,
    validate_step_2b_monologue,
    validate_step_3_phrases,
)
from tests.unit._policy_fixtures import _good_lesson


class TestDepthRatios:
    def test_compliant_lesson_passes(self):
        assert validate_lesson_depth(_good_lesson()) == []

    def test_step_2a_too_short_flagged(self):
        l = _good_lesson(step_2a_tell="Short.")
        errors = validate_lesson_depth(l)
        assert errors
        assert f"{STEP_2A_MIN_MULTIPLIER}" in errors[0]

    def test_step_2b_too_short_flagged(self):
        l = _good_lesson(step_2b_show="Too short for a think-aloud.")
        errors = validate_lesson_depth(l)
        assert errors
        assert f"{STEP_2B_MIN_MULTIPLIER}" in errors[0]

    def test_error_includes_target_word_count(self):
        l = _good_lesson(step_2b_show="Too short.")
        errors = validate_lesson_depth(l)
        # Should tell the model what length to target.
        assert "target" in errors[0].lower() and "words" in errors[0]

    def test_empty_step_1_is_not_a_depth_error(self):
        # Structural validator handles empty-step errors; depth validator
        # should just no-op so it doesn't produce misleading messages.
        l = _good_lesson(step_1_introduce="")
        assert validate_lesson_depth(l) == []


class TestStep3Phrases:
    def test_all_four_present_passes(self):
        assert validate_step_3_phrases(_good_lesson()) == []

    def test_one_missing_flagged(self):
        # Remove 'back to me' from step 3.
        step_3_missing = (
            "Now let's help me with the next sentence together. "
            "Turn and talk with your partner. "
            "This is some of what you might say."
        )
        l = _good_lesson(step_3_interact=step_3_missing)
        errors = validate_step_3_phrases(l)
        assert errors
        assert "back to me" in errors[0]

    def test_all_four_missing_flags_all(self):
        l = _good_lesson(step_3_interact="Students practice.")
        errors = validate_step_3_phrases(l)
        assert errors
        for phrase in STEP_3_REQUIRED_PHRASES:
            assert phrase in errors[0]

    def test_case_insensitive_match(self):
        step_3 = (
            "Help Me With The Next example. TURN AND TALK with your neighbor. "
            "Back To Me. This Is Some Of What you might say: However, "
            "my favorite flavor is chocolate because of its rich, deep taste."
        )
        l = _good_lesson(step_3_interact=step_3)
        assert validate_step_3_phrases(l) == []

    # ---- Phase 16.4 tail-content requirement for 'this is some of what' ----

    def test_dangling_cue_with_no_tail_is_flagged(self):
        """R3-adjacent regression: model sometimes satisfies the literal
        cue substring but leaves nothing after it, producing a half-sentence
        that does not meet Brady's B-G09 modeled-answer requirement."""
        step_3 = (
            "Help me with the next sentence. Turn and talk with your "
            "partner about where a transition fits. Back to me. "
            "This is some of what."
        )
        l = _good_lesson(step_3_interact=step_3)
        errors = validate_step_3_phrases(l)
        assert errors
        assert "modeled teacher answer" in errors[0]

    def test_cue_followed_by_only_punctuation_is_flagged(self):
        step_3 = (
            "Help me with the next sentence. Turn and talk. Back to me. "
            "This is some of what... ??? !"
        )
        l = _good_lesson(step_3_interact=step_3)
        errors = validate_step_3_phrases(l)
        assert errors
        assert "modeled teacher answer" in errors[0]

    def test_cue_followed_by_substantial_tail_passes(self):
        step_3 = (
            "Help me with the next one. Turn and talk. Back to me. "
            "This is some of what I heard from you: However, my favorite "
            "flavor is chocolate because of its rich, deep taste."
        )
        l = _good_lesson(step_3_interact=step_3)
        assert validate_step_3_phrases(l) == []

    def test_missing_cue_does_not_doubly_report_tail(self):
        """If the cue itself is absent, the tail check must not fire —
        the missing-cue error is already sufficient feedback and a tail
        error on top would be noise."""
        step_3 = (
            "Help me with the next sentence. Turn and talk. Back to me. "
            "That was a great share."  # cue absent
        )
        l = _good_lesson(step_3_interact=step_3)
        errors = validate_step_3_phrases(l)
        assert len(errors) == 1
        assert "this is some of what" in errors[0]
        assert "modeled teacher answer" not in errors[0]


class TestStep2BMonologue:
    def test_two_or_more_phrases_passes(self):
        # Good lesson has several monologue phrases.
        assert validate_step_2b_monologue(_good_lesson()) == []

    def test_zero_phrases_flagged(self):
        l = _good_lesson(
            step_2b_show=(
                "The teacher demonstrates by writing a sample sentence "
                "on the board. The class watches. "
                "The teacher reads the sentence aloud. "
                "The teacher adds a transition. "
                "The teacher rereads the sentence to check the flow."
            )
        )
        errors = validate_step_2b_monologue(l)
        assert errors
        assert "monologue" in errors[0].lower()

    def test_one_phrase_flagged_as_insufficient(self):
        l = _good_lesson(
            step_2b_show=(
                "I wonder what transition I should use. "
                "The teacher writes a sample on the board. "
                "The class watches carefully. "
                "The teacher reads it aloud. "
                "The sentence is then revised."
            )
        )
        errors = validate_step_2b_monologue(l)
        assert errors
        # Must mention the shortfall (found N < required).
        assert "Found 1" in errors[0] or "Found " in errors[0]
