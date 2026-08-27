"""Tests for validation/endings.py (Wave 0 Part 2 test colocation)."""
from __future__ import annotations

import pytest

from validation.endings import (
    HOW_TO_TEACH_MULTI_SKILL_CLOSER,
    HOW_TO_TEACH_MULTI_SKILL_CLOSER_FRAGMENT,
    ends_with_offer_question,
    is_offer_eligible,
    required_closing_phrases,
    scripted_ml_grade_band,
    validate_grade_band_close,
    validate_response_ending,
)
from tests.unit._policy_fixtures import _good_lesson


class TestResponseEnding:
    @pytest.mark.parametrize(
        "qt,phrase",
        [
            ("HOW_TO_TEACH", "Are you ready for a scripted mini-lesson?"),
            # Brady x1 (docx paras 32-33, RED "Good"; video @5682) — see
            # test_plan_unit_closes_with_bradys_outline_offer below.
            ("PLAN_UNIT", "Is this helpful? Would you like a general outline of this unit?"),
            ("COACHING_GENERAL", "Does this make sense? Is this helpful?"),
            # Brady E3: MANAGEMENT now closes with the overview closer, not the
            # generic coaching closer.
            ("MANAGEMENT", "This was an overview. Which ONE area or SINGLE routine would you like to start with?"),
        ],
    )
    def test_correct_ending_passes(self, qt, phrase):
        resp = f"Some body text about the skill. {phrase}"
        assert validate_response_ending(qt, resp) == []

    def test_plan_unit_old_closer_now_rejected(self):
        # The pre-Wave-2c closer ("Do you want a lesson to teach one of these
        # skills?") has no Brady provenance and must not satisfy the validator.
        old = (
            "For 5th grade persuasive writing, here are the priority skills. "
            "Do you want a lesson to teach one of these skills?"
        )
        errors = validate_response_ending("PLAN_UNIT", old)
        assert errors
        assert "PLAN_UNIT" in errors[0]

    def test_plan_unit_closes_with_bradys_outline_offer(self):
        """x1 — Brady's response-shapes table, `feedback.docx` para 33.

        Verified in the RAW docx (the extracted text drops all 72 snips, so a
        quote from it is unanchored — that is how this defect was born):

            para 31  "Response shapes:"
            para 32  "'Plan a unit' gets list of priority skills."
            para 33  "To be followed by 'Is this helpful? Would you like a
                      general outline of this unit?'  Good"

        "Good" is run-colour EE0000 = RED = his "feedback and reflections on
        your revisions" — i.e. he tested this shape and signed it off. The
        video corroborates it verbatim (@5682).
        """
        resp = (
            "For 5th grade persuasive writing, here are the priority skills in order:\n\n"
            "1. Recognize opinion topics\n"
            "2. Determine the strongest side\n\n"
            "Is this helpful? Would you like a general outline of this unit?"
        )
        assert validate_response_ending("PLAN_UNIT", resp) == []

    def test_plan_unit_rejects_the_how_to_teach_refinement(self):
        """x1 — "Which of these skills..." is Brady's HOW_TO_TEACH closer, not
        PLAN_UNIT's, and must not satisfy PLAN_UNIT's ending.

        Wave 2c (E5b) lifted it onto PLAN_UNIT from `feedback.docx` para 332,
        which annotates `word/media/image52.png` — a snip of a HOW_TO_TEACH
        exchange ("I'm getting ready to teach how to write from sources" ->
        "Which grade level are you teaching?" -> "7th" -> a 5-skill outline),
        where Brady highlighted the closer glued to item 5. He narrates that
        exact snip at transcript @40869: "I jumped up to secondary grades...
        'Are you ready for a scripted mini lesson?' Again, separate that
        skill." The refinement belongs to multi-skill HOW_TO_TEACH outlines.
        """
        resp = (
            "For 5th grade persuasive writing, here are the priority skills. "
            "Which of these skills do you want to start with? "
            "You can't teach them all in a single lesson."
        )
        errors = validate_response_ending("PLAN_UNIT", resp)
        assert errors
        assert "PLAN_UNIT" in errors[0]

    def test_management_old_generic_closer_now_rejected(self):
        # Brady E3 (28:30, doc 128): a MANAGEMENT overview now closes with
        # "This was an overview. Which ONE area or SINGLE routine would you
        # like to start with?" The OLD generic "Does this make sense? Is this
        # helpful?" closer must NO LONGER satisfy the validator for MANAGEMENT
        # — it is not the E3 phrase and (unlike a concrete next-step offer)
        # carries no offer stem, so the E4 offer path does not rescue it.
        old = (
            "Here are the writers'-workshop routines to set up first. "
            "Does this make sense? Is this helpful?"
        )
        errors = validate_response_ending("MANAGEMENT", old)
        assert errors
        assert "MANAGEMENT" in errors[0]

    def test_management_overview_closer_passes(self):
        # The E3 overview closer satisfies the MANAGEMENT ending requirement.
        resp = (
            "Set up folders, post the schedule, and teach the Help Desk. "
            "This was an overview. Which ONE area or SINGLE routine would you "
            "like to start with?"
        )
        assert validate_response_ending("MANAGEMENT", resp) == []

    def test_management_required_phrase_is_e3_overview_closer(self):
        # The registered MANAGEMENT closer is the E3 overview closer, keyed on
        # its distinctive fragments — NOT the generic coaching closer.
        phrases = required_closing_phrases("MANAGEMENT")
        assert any(
            p in ("this was an overview", "which one area", "single routine")
            for p in phrases
        )
        assert "does this make sense" not in phrases
        assert "is this helpful" not in phrases

    @pytest.mark.parametrize("qt", ["COACHING_GENERAL", "MANAGEMENT"])
    def test_offer_as_single_closing_question_accepted(self, qt):
        # Brady E4: a concrete next-step offer is an acceptable SINGLE
        # closing question on its own — the model must not be forced to
        # stack the generic "Does this make sense? Is this helpful?" on
        # top of it. This is additive: the generic closer alone (tested
        # above) must still be accepted too.
        resp = "Here's a great plan. Want me to map out a week of lessons?"
        assert validate_response_ending(qt, resp) == []

    @pytest.mark.parametrize(
        "qt,resp",
        [
            # "ready for" appears mid-sentence in a DECLARATIVE close — no
            # closing question at all. The offer path must NOT accept this;
            # doing so would reintroduce the missing-ending defect.
            (
                "MANAGEMENT",
                "Remind them your writers are ready for independent work "
                "once the mini-lesson ends.",
            ),
            (
                "COACHING_GENERAL",
                "Once they master this move, your writers are ready for "
                "independent revision.",
            ),
        ],
    )
    def test_declarative_offer_phrase_without_question_still_errors(self, qt, resp):
        # An offer phrase buried in a declarative sentence is NOT a closing
        # question. Acceptance is anchored to a tail that actually ENDS in
        # "?" — otherwise "ready for"/"do you want" in body prose would let a
        # question-less response slip through.
        errors = validate_response_ending(qt, resp)
        assert errors
        assert qt in errors[0]

    @pytest.mark.parametrize("qt", ["COACHING_GENERAL", "MANAGEMENT"])
    def test_bare_non_offer_question_still_errors(self, qt):
        # A closing question that is NOT the generic closer and NOT an
        # offer ("What do you think?") is not an accepted ending for these
        # query_types — the offer path only accepts an actual offer phrase.
        resp = "That covers the strategy. What do you think?"
        errors = validate_response_ending(qt, resp)
        assert errors
        assert qt in errors[0]

    def test_offer_phrase_scoped_to_coaching_and_management_only(self):
        # HOW_TO_TEACH has its OWN required closing phrase ("are you ready
        # for a scripted mini-lesson"). A generic offer phrase must NOT
        # satisfy it — the offer-acceptance path is scoped to
        # COACHING_GENERAL/MANAGEMENT only, not a blanket exemption for
        # every query_type.
        resp = "Here's how to teach it. Want me to help?"
        errors = validate_response_ending("HOW_TO_TEACH", resp)
        assert errors
        assert "are you ready for a scripted mini-lesson" in errors[0].lower()

    def test_coaching_general_without_generic_or_offer_still_errors(self):
        # Neither the generic closer NOR an offer phrase is present — must
        # still fail. The offer path is an alternative closing, not a free
        # pass on having a closing question at all.
        resp = "Some body text about the skill. But no closing question here."
        errors = validate_response_ending("COACHING_GENERAL", resp)
        assert errors
        assert "COACHING_GENERAL" in errors[0]
        assert "does this make sense" in errors[0].lower()

    def test_scripted_ml_has_no_generic_ending_requirement(self):
        # SCRIPTED_ML intentionally has no _ENDING_REQUIRED entry — its close
        # is grade-band specific (K-2 vs 3-12), not a single fixed phrase, so
        # it can't be checked by this generic query_type -> phrase(s) map.
        # Enforcement lives in validate_grade_band_close (below), wired into
        # validate_lesson_policy — NOT here.
        assert validate_response_ending("SCRIPTED_ML", "Lesson text, no closing phrase.") == []

    def test_missing_ending_flagged(self):
        resp = "Body text about the skill. But no required closing phrase here."
        errors = validate_response_ending("HOW_TO_TEACH", resp)
        assert errors
        assert "are you ready for a scripted mini-lesson" in errors[0].lower()

    def test_ending_buried_beyond_window_flagged(self):
        long_body = ("Filler. " * 120)  # > 500 chars of filler
        resp = "Are you ready for a scripted mini-lesson? " + long_body
        errors = validate_response_ending("HOW_TO_TEACH", resp)
        # Required ending is at the top, not the end — should fail.
        assert errors


def test_required_closing_phrases_returns_registered_and_empty() -> None:
    from validation.endings import required_closing_phrases
    assert "are you ready for a scripted mini-lesson" in required_closing_phrases("HOW_TO_TEACH")
    assert required_closing_phrases("SCRIPTED_ML") == ()   # no registered closer
    assert required_closing_phrases("NONSENSE") == ()


# ----------------------------------------------------------------------
# Brady C8 — HOW_TO_TEACH accepts BOTH closers (single- and multi-skill)
# ----------------------------------------------------------------------
#
# A HOW_TO_TEACH outline that enumerates >1 sub-skill closes with Brady's
# multi-skill pick-list closer ("Which of these skills do you want to start
# with? You can't teach them all in a single lesson."), NOT the single-skill
# "...on this skill?" — "this skill" has no referent when several skills were
# just listed (docx para 332, image52.png; @40869). The delivery-seam EMITTER
# (_swap_multi_skill_closer) performs the swap; the validator must ACCEPT the
# result, so both closers are registered for HOW_TO_TEACH. The multi-skill
# fragment is derived from the emitted constant so the two can never drift.


class TestHowToTeachMultiSkillCloser:
    def test_single_skill_closer_still_accepted(self) -> None:
        resp = "Here's how to teach it. Are you ready for a scripted mini-lesson on this skill?"
        assert validate_response_ending("HOW_TO_TEACH", resp) == []

    def test_multi_skill_closer_accepted(self) -> None:
        resp = f"Here are the priority sub-skills. {HOW_TO_TEACH_MULTI_SKILL_CLOSER}"
        assert validate_response_ending("HOW_TO_TEACH", resp) == []

    def test_both_fragments_registered_for_how_to_teach(self) -> None:
        phrases = required_closing_phrases("HOW_TO_TEACH")
        assert "are you ready for a scripted mini-lesson" in phrases
        assert HOW_TO_TEACH_MULTI_SKILL_CLOSER_FRAGMENT in phrases

    def test_multi_skill_fragment_is_derived_from_the_constant(self) -> None:
        # The registered validator fragment is the emitted constant's first
        # sentence, lowercased — so the emitter and validator cannot drift.
        assert HOW_TO_TEACH_MULTI_SKILL_CLOSER_FRAGMENT == (
            "which of these skills do you want to start with"
        )
        assert HOW_TO_TEACH_MULTI_SKILL_CLOSER.lower().startswith(
            HOW_TO_TEACH_MULTI_SKILL_CLOSER_FRAGMENT
        )

    def test_multi_skill_closer_is_bradys_verbatim_phrase(self) -> None:
        # Guards the exact wording Brady approved (VERBATIM) against a reword.
        assert HOW_TO_TEACH_MULTI_SKILL_CLOSER == (
            "Which of these skills do you want to start with? "
            "You can't teach them all in a single lesson."
        )

    def test_multi_skill_closer_does_not_satisfy_plan_unit(self) -> None:
        # The multi-skill closer belongs to HOW_TO_TEACH, not PLAN_UNIT (x1).
        resp = f"For 3rd grade, here are the priority skills. {HOW_TO_TEACH_MULTI_SKILL_CLOSER}"
        errors = validate_response_ending("PLAN_UNIT", resp)
        assert errors
        assert "PLAN_UNIT" in errors[0]


class TestGradeBandClose:
    """Brady E1 / non-negotiable #10 (Wave 1a Task 4, flips F60): a SCRIPTED_ML
    lesson's Step 4 close must be grade-band specific — K-2 ends "Let's go be
    writers!"; grades 3-12 end "Now it's your turn!". Previously any lesson
    could end "Let's go be writers!" (or omit a close) regardless of grade —
    that was the F60 bug this validator fixes."""

    def test_grade_band_helper(self):
        assert scripted_ml_grade_band("1") == "K-2"
        assert scripted_ml_grade_band("7") == "3-12"
        assert scripted_ml_grade_band("K-2") == "K-2"

    def test_grade_band_helper_covers_every_band_and_default(self):
        # K-2 side: every individual grade + the band literal.
        for g in ("K", "1", "2", "K-2"):
            assert scripted_ml_grade_band(g) == "K-2"
        # 3-12 side: every specific grade + every other clean band, plus the
        # "unknown grade" default (None / "") — a scripted ML is grade-
        # specific in practice, so the safer default is the stricter band,
        # not silence.
        for g in ("3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
                   "3-5", "6-8", "9-12", "K-12", "all", None, ""):
            assert scripted_ml_grade_band(g) == "3-12"

    def test_3_12_requires_now_its_your_turn(self):
        lesson = _good_lesson(step_4_close="Great work today.")  # no phrase
        assert validate_grade_band_close(lesson, "3-12")
        ok = _good_lesson(step_4_close="Great work. Now it's your turn!")
        assert validate_grade_band_close(ok, "3-12") == []

    def test_k2_requires_lets_go_be_writers(self):
        ok = _good_lesson(step_4_close="Let's go be writers!")
        assert validate_grade_band_close(ok, "K-2") == []

    def test_k2_flags_wrong_bands_phrase(self):
        # The 3-12 phrase does NOT satisfy the K-2 requirement — the two
        # bands are not interchangeable.
        wrong = _good_lesson(step_4_close="Great work. Now it's your turn!")
        errors = validate_grade_band_close(wrong, "K-2")
        assert errors
        assert "Brady E1" in errors[0]
        assert "Let's go be writers!" in errors[0]

    def test_3_12_flags_wrong_bands_phrase(self):
        # Mirror of the K-2 case: the K-2 phrase alone does NOT satisfy the
        # 3-12 requirement — the bands are not interchangeable either way.
        wrong = _good_lesson(step_4_close="Great work. Let's go be writers!")
        errors = validate_grade_band_close(wrong, "3-12")
        assert errors
        assert "Brady E1" in errors[0]
        assert "Now it's your turn!" in errors[0]

    def test_smart_apostrophe_close_accepted(self):
        # LLMs routinely emit the Unicode right single quote (U+2019) in
        # contractions. A smart-quoted but otherwise-correct close must NOT
        # be falsely flagged on Brady's non-negotiable #10.
        ok_3_12 = _good_lesson(step_4_close="Great work. Now it’s your turn!")
        assert validate_grade_band_close(ok_3_12, "3-12") == []
        ok_k2 = _good_lesson(step_4_close="Let’s go be writers!")
        assert validate_grade_band_close(ok_k2, "K-2") == []

    def test_error_message_names_the_band(self):
        lesson = _good_lesson(step_4_close="No closing phrase at all.")
        errors = validate_grade_band_close(lesson, "3-12")
        assert "3-12" in errors[0]
        assert "Now it's your turn!" in errors[0]


# ----------------------------------------------------------------------
# Offer-close single source of truth (Wave 2c — Brady E4)
# ----------------------------------------------------------------------
#
# ends_with_offer_question / is_offer_eligible are the ONE definition of
# "a valid concrete-offer closing question" and "which query_types may use
# one". Both validate_response_ending (E4 acceptance) and the delivery-seam
# _dedupe_closing_question (E4 dedup) consume them, so the acceptance rule
# and the normalizer can never drift apart. The regex is widened to cover
# natural offer stems ("Can I ...?", "How about I ...?", "Would it help ...?"),
# not just Brady's single example phrasing.


class TestOfferSoT:
    def test_ends_with_offer_question_true(self):
        assert ends_with_offer_question("Sure. Want me to map a week?")

    def test_ends_with_offer_question_widened(self):
        # "Can I ...?" is a natural offer the widened regex must now accept.
        assert ends_with_offer_question("Great. Can I map out a week?")

    def test_ends_with_offer_question_false_declarative(self):
        # No question at all -> not an offer close.
        assert not ends_with_offer_question("That works well.")

    def test_ends_with_offer_question_false_non_question(self):
        # Offer stem present but the sentence is declarative (ends "."), so
        # it is NOT a closing question.
        assert not ends_with_offer_question("Want me to help you plan.")

    def test_is_offer_eligible(self):
        assert is_offer_eligible("COACHING_GENERAL")
        assert is_offer_eligible("MANAGEMENT")
        assert not is_offer_eligible("HOW_TO_TEACH")

    def test_validate_ending_still_accepts_offer_close(self):
        # The refactor onto the SoT helpers is behavior-preserving: an offer
        # question still satisfies the COACHING_GENERAL ending requirement.
        assert validate_response_ending(
            "COACHING_GENERAL", "Advice here. Want me to map a week?"
        ) == []
