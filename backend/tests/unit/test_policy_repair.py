"""Unit tests for Phase 11.9 — policy error classifier + repair instructions.

The classifier is prefix-coupled to ``validation/policy.py``'s message
wording. If a validator's message changes, the corresponding test here
fails loudly so the coupling is caught during development rather than in
production. That's the whole reason for this file.
"""

from __future__ import annotations

import pytest

from generation.lesson import MiniLesson
from validation.policy import (
    LessonPolicyResult,
    validate_lesson_policy,
    validate_no_forbidden_words,
    validate_response_ending,
    validate_step_3_phrases,
)
from validation.policy_repair import (
    RepairKind,
    classify_error,
    extract_repair_instructions,
    partition_repairable,
    sort_errors_by_priority,
)


# ---------------------------------------------------------------------------
# Classifier — shape of each validator's output maps to the right RepairKind
# ---------------------------------------------------------------------------


class TestClassifyFromRealValidators:
    """Feed the classifier strings emitted by real validators. If any of
    these fail, a validator's message wording drifted — that IS the bug."""

    def test_forbidden_word_output_is_classified_forbidden(self):
        errors = validate_no_forbidden_words(
            "let's discuss the topic and keep going"
        )
        assert errors, "validator must flag the forbidden word"
        assert classify_error(errors[0]) is RepairKind.FORBIDDEN_WORD

    def test_step3_missing_phrase_is_classified_step3(self):
        lesson = MiniLesson(
            skill_focus="x", grade_level="3", writing_mode="Inform",
            step_1_introduce="hi", step_2a_tell="a", step_2b_show="b",
            step_3_interact="turn and talk. back to me. this is some of what",
            step_4_close="end",
        )
        errors = validate_step_3_phrases(lesson)
        assert errors, "validator must flag the missing 'help me with the next'"
        assert classify_error(errors[0]) is RepairKind.MISSING_STEP3_PHRASE

    def test_missing_ending_is_classified_ending(self):
        errors = validate_response_ending(
            "COACHING_GENERAL",
            "This is my response with no closing prompt.",
        )
        assert errors
        assert classify_error(errors[0]) is RepairKind.MISSING_ENDING


class TestClassifyOther:
    """Errors from validators we don't repair must be classified OTHER."""

    def test_depth_error_is_other(self):
        err = (
            "Step 2B is too short (50 words). It must be at least 4.0× the "
            "length of Step 1 (20 words)..."
        )
        assert classify_error(err) is RepairKind.OTHER

    def test_monologue_error_is_other(self):
        err = (
            "Step 2B must contain at least 2 internal-monologue phrases. "
            "Found 0..."
        )
        assert classify_error(err) is RepairKind.OTHER

    def test_empty_string_is_other(self):
        assert classify_error("") is RepairKind.OTHER

    def test_unrelated_text_is_other(self):
        assert classify_error("some random log line") is RepairKind.OTHER


# ---------------------------------------------------------------------------
# partition_repairable
# ---------------------------------------------------------------------------


class TestPartitionRepairable:
    def test_empty_input_yields_two_empty_lists(self):
        r, s = partition_repairable([])
        assert r == [] and s == []

    def test_mixed_errors_split_correctly(self):
        errors = [
            "Forbidden word 'discuss'. ...",
            "Step 2B is too short (40 words). ...",  # structural
            "Response for query_type=COACHING_GENERAL must end with one of ['a']. ...",
            "skill_focus must preserve the teacher's wording ('X'). ...",  # other
        ]
        repairable, structural = partition_repairable(errors)
        assert len(repairable) == 2
        assert len(structural) == 2
        # Check actual contents — don't rely on ordering beyond stability.
        assert any("discuss" in e for e in repairable)
        assert any("must end with" in e for e in repairable)
        assert any("Step 2B is too short" in e for e in structural)
        assert any("skill_focus" in e for e in structural)

    def test_preserves_within_category_order(self):
        """Stability matters — if the model sees 'fix forbidden X then
        forbidden Y' in that order, we want to hand it the instructions in
        that order too."""
        errors = [
            "Forbidden word 'discuss'. ...",
            "Forbidden word 'activity'. ...",
        ]
        repairable, _ = partition_repairable(errors)
        assert "discuss" in repairable[0]
        assert "activity" in repairable[1]


# ---------------------------------------------------------------------------
# extract_repair_instructions — shape of the instructions the prompt gets
# ---------------------------------------------------------------------------


class TestExtractInstructions:
    def test_forbidden_word_instruction_names_the_word_and_replacement(self):
        errs = [
            "Forbidden word 'discuss'. Smekens methodology "
            "forbids this word in EVERY context, including variations and "
            "inflections. Replace with: 'turn and talk' (Smekens protocol). "
            "Re-scan the entire response and remove ALL occurrences."
        ]
        instructions = extract_repair_instructions(errs)
        assert len(instructions) == 1
        text = instructions[0]
        assert "'discuss'" in text
        # Replacement hint included so the LLM has a concrete swap.
        assert "turn and talk" in text
        # Editor framing — avoids the model "creatively" rewriting neighbors.
        assert "Do not reword anything else" in text

    def test_step3_instruction_lists_the_missing_phrases(self):
        errs = [
            "Step 3 is missing the required Smekens phrase(s): "
            "'help me with the next'. These are EXACT character-for-character "
            "substrings — do NOT paraphrase..."
        ]
        instructions = extract_repair_instructions(errs)
        assert len(instructions) == 1
        assert "'help me with the next'" in instructions[0]
        assert "EXACT substring" in instructions[0]

    def test_ending_instruction_names_the_approved_endings(self):
        errs = [
            "Response for query_type=COACHING_GENERAL must end with one of "
            "['does this make sense', 'is this helpful']. Current ending "
            "(last 500 chars): ...'whatever'"
        ]
        instructions = extract_repair_instructions(errs)
        assert len(instructions) == 1
        assert "['does this make sense', 'is this helpful']" in instructions[0]

    def test_unknown_error_kinds_are_silently_dropped(self):
        """Callers partition first and pass only repairable errors — but the
        extractor should be defensive and skip anything it doesn't know how
        to handle rather than crashing."""
        errs = [
            "Forbidden word 'discuss'. ...",
            "Step 2B is too short ...",  # OTHER — should be skipped
        ]
        instructions = extract_repair_instructions(errs)
        assert len(instructions) == 1
        assert "'discuss'" in instructions[0]

    def test_empty_input_yields_empty_instructions(self):
        assert extract_repair_instructions([]) == []


# ---------------------------------------------------------------------------
# sort_errors_by_priority — feedback ordering tweak
# ---------------------------------------------------------------------------


class TestSortByPriority:
    def test_forbidden_words_come_before_other_categories(self):
        errors = [
            "Step 2B is too short...",  # OTHER
            "Forbidden word 'discuss'. ...",  # FORBIDDEN
            "Step 3 is missing the required Smekens phrase(s): 'x'...",  # STEP3
            "Response for query_type=X must end with one of [...]...",  # ENDING
        ]
        sorted_errors = sort_errors_by_priority(errors)
        assert "forbidden word" in sorted_errors[0].lower()
        assert "Step 3 is missing" in sorted_errors[1]
        assert "must end with" in sorted_errors[2]
        assert "too short" in sorted_errors[3]

    def test_stable_within_category(self):
        """Two forbidden-word errors keep their scan order."""
        errors = [
            "Forbidden word 'discuss'. ...",
            "Forbidden word 'activity'. ...",
        ]
        out = sort_errors_by_priority(errors)
        assert "discuss" in out[0]
        assert "activity" in out[1]

    def test_feedback_block_uses_priority_order(self):
        """The LessonPolicyResult.as_feedback_block() must reflect the new
        priority ordering so retries get forbidden-words first."""
        result = LessonPolicyResult(errors=[
            "Step 2B is too short...",
            "Forbidden word 'discuss'. ...",
        ])
        block = result.as_feedback_block().lower()
        forbidden_pos = block.find("forbidden word")
        depth_pos = block.find("too short")
        assert forbidden_pos != -1 and depth_pos != -1
        assert forbidden_pos < depth_pos, (
            "Forbidden-word error must appear BEFORE depth error in "
            "feedback block — LLMs attend more to earlier constraints."
        )


# ---------------------------------------------------------------------------
# End-to-end classification of a real validator-produced error list
# ---------------------------------------------------------------------------


class TestEndToEndFlow:
    def test_real_policy_result_classifies_cleanly(self):
        """Construct a lesson with deliberate violations, run the real
        ``validate_lesson_policy`` chain, and confirm each error in the
        output maps to a non-OTHER RepairKind for the ones we care about."""
        lesson = MiniLesson(
            skill_focus="topic sentences",
            grade_level="3",
            writing_mode="Inform",
            step_1_introduce="Short intro.",
            step_2a_tell=(
                "A reasonably long TELL section with enough words to satisfy "
                "the depth requirement — " + "word " * 40
            ),
            step_2b_show=(
                "I close my eyes and think. Hmm. " + "word " * 40
            ),
            step_3_interact=(
                "Now let's discuss this together. Turn and talk. Back to me. "
                "This is some of what I heard."
            ),  # forbidden 'discuss' + missing 'help me with the next'
            step_4_close="Great work today. No closing prompt here.",
        )
        result = validate_lesson_policy(
            lesson,
            retrieved_context="",
            response_text=lesson.model_dump_json(),
            user_skill_phrase="",
        )
        # We expect at least one FORBIDDEN_WORD and one MISSING_STEP3_PHRASE.
        kinds = {classify_error(e) for e in result.errors}
        assert RepairKind.FORBIDDEN_WORD in kinds
        assert RepairKind.MISSING_STEP3_PHRASE in kinds

        repairable, structural = partition_repairable(result.errors)
        # Everything classified as non-OTHER above should be in repairable;
        # nothing should be lost in transit.
        assert len(repairable) + len(structural) == len(result.errors)
