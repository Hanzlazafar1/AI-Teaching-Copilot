"""Generation acceptance tests — BRADY-ALIGNMENT-PLAN.md Section 7.2 (TG01-TG15).

Verify generation output matches Brady's specific requirements:
- Step 2B depth (≥3× Step 1 — enforced floor; prompt aims 4×) + think-aloud language [B-G01, B-G02]
- Step 3 sentence starters [B-G08, B-G09]
- Forbidden words (discuss, activity, "I'll listen in") [B-P01, B-P02]
- Book + page + digital resources citation [B-P05]
- Query-type-specific endings [B-F02]
- User vocab preservation [B-G12]
- Smekens trigger usage [B-G06]

All tests expected to FAIL before Phase 9-10 are implemented.
"""

from __future__ import annotations

import re

import pytest

from validation.policy import STEP_2B_MIN_MULTIPLIER
from tests.acceptance.conftest import (
    API_BASE,
    _backend_available,
    assert_book_citation_present,
    assert_lesson_step_ratio,
    assert_no_forbidden_words,
    assert_response_ends_with_any,
    assert_skill_focus_preserves,
    assert_step_2b_has_internal_monologue,
    assert_step_3_has_required_phrases,
)


# ---------------------------------------------------------------------------
# SCRIPTED_ML depth + sentence starters [B-G01, B-G02, B-G08, B-G09]
# ---------------------------------------------------------------------------


class TestScriptedMLDepth:
    @pytest.mark.acceptance
    def test_TG01_step_lengths(self, chat) -> None:
        """Step 2A ≥ 2× Step 1 AND Step 2B ≥ 3× Step 1 — enforced floor; prompt aims 4× [B-G01]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on using strong verbs for 5th graders"
        )
        assert resp.is_lesson, f"Expected MiniLesson response, got: {resp.text[:200]}"
        # Brady 3× decision (2026-07-10): the enforced Step-2B floor is 3×
        # (STEP_2B_MIN_MULTIPLIER); the prompt still aims for 4×. Assert the
        # enforced floor so TG01 tracks the validator instead of flaking on a
        # 3.x× (fully compliant) lesson.
        assert_lesson_step_ratio(
            resp,
            step_2b_over_step_1=STEP_2B_MIN_MULTIPLIER,
            step_2a_over_step_1=2.0,
        )

    @pytest.mark.acceptance
    def test_TG02_step_2b_internal_monologue(self, chat) -> None:
        """Step 2B must contain ≥2 internal monologue phrases [B-G02]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on using strong verbs for 5th graders"
        )
        assert resp.is_lesson, f"Expected MiniLesson response, got: {resp.text[:200]}"
        assert_step_2b_has_internal_monologue(resp)

    @pytest.mark.acceptance
    def test_TG03_step_3_help_me_with_next(self, chat) -> None:
        """Step 3 opens with 'help me with the next one' [B-G08]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on transitions for 4th graders"
        )
        assert resp.is_lesson
        s3 = (resp.lesson.get("step_3_interact") or "").lower()
        assert "help me with the next" in s3, (
            f"Step 3 must contain 'help me with the next'. Got: {s3[:200]!r}"
        )

    @pytest.mark.acceptance
    def test_TG04_step_3_all_required_phrases(self, chat) -> None:
        """Step 3 includes: 'turn and talk', 'back to me', 'this is some of what' [B-G09]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on transitions for 4th graders"
        )
        assert resp.is_lesson
        assert_step_3_has_required_phrases(resp)


# ---------------------------------------------------------------------------
# Forbidden words [B-P01, B-P02, TG14]
# ---------------------------------------------------------------------------


class TestForbiddenWords:
    @pytest.mark.acceptance
    def test_TG05_no_discuss(self, chat) -> None:
        """Response must not contain the word 'discuss' [B-P01]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on topic sentences for 3rd grade"
        )
        assert_no_forbidden_words(resp, ["discuss"])

    @pytest.mark.acceptance
    def test_TG06_no_activity(self, chat) -> None:
        """Response must not contain the word 'activity' [B-P02]."""
        resp = chat.send(
            "Plan a persuasive unit for 4th grade"
        )
        assert_no_forbidden_words(resp, ["activity"])

    @pytest.mark.acceptance
    def test_TG14_no_ill_listen_in(self, chat) -> None:
        """Response must not contain 'I'll listen in' [B-G11]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on using strong verbs for 5th graders"
        )
        text = resp.text.lower()
        assert "i'll listen in" not in text, (
            f"Response contains forbidden phrase 'I'll listen in'. Text: {text[:300]!r}"
        )


# ---------------------------------------------------------------------------
# Book citation [B-P05]
# ---------------------------------------------------------------------------


class TestBookCitation:
    @pytest.mark.acceptance
    def test_TG07_page_and_digital_resources(self, chat) -> None:
        """Launch book citation must include numeric page + book name + 'digital resources' [B-P05]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on Snapple details for 6th grade"
        )
        assert_book_citation_present(resp)


# ---------------------------------------------------------------------------
# User vocab preservation [B-G12]
# ---------------------------------------------------------------------------


class TestUserVocabPreservation:
    @pytest.mark.acceptance
    def test_TG08_preserve_topic_sentence_phrase(self, chat) -> None:
        """skill_focus must contain 'topic sentence' exactly as user said it [B-G12]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on topic sentence and supporting details for 3rd grade"
        )
        assert resp.is_lesson, f"Expected MiniLesson. Got: {resp.text[:200]}"
        assert_skill_focus_preserves(resp, "topic sentence")


# ---------------------------------------------------------------------------
# Smekens trigger usage [B-G06, TG09, TG15]
# ---------------------------------------------------------------------------


class TestSmekensTriggerUsage:
    @pytest.mark.acceptance
    def test_TG09_pizza_table_trigger_in_output(self, chat) -> None:
        """When pizza table is the trigger, output mentions 'table-top' or 'legs' [B-G06]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on topic sentence and supporting details for 3rd grade"
        )
        text = resp.text.lower()
        assert "table-top" in text or "table top" in text or "legs" in text, (
            f"Expected Smekens trigger 'table-top' or 'legs'. Got text preview: {text[:400]!r}"
        )

    @pytest.mark.acceptance
    def test_TG15_how_to_teach_mentions_trigger(self, chat) -> None:
        """HOW_TO_TEACH outline for paragraphing must name the pizza-table/table-top trigger [B-R03, B-G06]."""
        resp = chat.send("How do I teach paragraph writing to 3rd graders?")
        text = resp.text.lower()
        # Should mention the trigger explicitly
        assert any(
            term in text
            for term in ["table-top", "table top", "legs", "pizza"]
        ), f"HOW_TO_TEACH must name the trigger. Got: {text[:500]!r}"


# ---------------------------------------------------------------------------
# Response endings per query type [B-F02]
# ---------------------------------------------------------------------------


class TestResponseEndings:
    @pytest.mark.acceptance
    def test_TG10_scripted_ml_ending(self, chat) -> None:
        """SCRIPTED_ML output ending is optional but if present is approved prompt [B-F02]."""
        resp = chat.send(
            "Give me a scripted mini-lesson on strong verbs for 5th grade"
        )
        # Optional: only assert no FORBIDDEN ending (PD sign-off)
        text = resp.text.lower()
        assert "professional development" not in text, (
            "Forbidden 'professional development' sign-off"
        )

    @pytest.mark.acceptance
    def test_TG11_how_to_teach_ending(self, chat) -> None:
        """A MULTI-skill HOW_TO_TEACH outline closes with the pick-list question
        ("Which of these skills do you want to start with? You can't teach them
        all in a single lesson.") — Brady x1 / image52; a single-skill outline
        keeps "…on this skill?" [B-F02]."""
        resp = chat.send("How do I teach topic sentences to 3rd graders?")
        assert_response_ends_with_any(
            resp,
            ["are you ready for a scripted mini-lesson",
             "which of these skills do you want to start with"],
            window=500,
        )

    @pytest.mark.acceptance
    def test_TG12_plan_unit_format_and_ending(self, chat) -> None:
        """PLAN_UNIT output is a skill list (not a 4-step ML) ending with Brady's approved closer 'Is this helpful? Would you like a general outline of this unit?' [B-F02, B-F01, x1]."""
        resp = chat.send("Plan a persuasive writing unit for 3rd grade")
        assert not resp.is_lesson, (
            "PLAN_UNIT should produce a skill list, not a 4-step ML"
        )
        text = resp.text
        assert re.search(r"^\s*\d+\.", text, re.MULTILINE), (
            f"PLAN_UNIT should contain a numbered skill list. Preview: {text[:300]!r}"
        )
        assert_response_ends_with_any(
            resp, ["general outline of this unit"], window=500
        )

    @pytest.mark.acceptance
    def test_TG13_coaching_general_ending(self, chat) -> None:
        """COACHING_GENERAL ends with ONE closing question — the generic
        'Does this make sense? Is this helpful?' OR (Brady E4) a concrete
        next-step offer. Mirror the production validator so the live test
        tracks the same contract instead of hardcoding the generic-only form."""
        from validation.endings import validate_response_ending

        resp = chat.send("What is the difference between revising and editing?")
        assert validate_response_ending("COACHING_GENERAL", resp.text) == [], (
            "E4: coaching must end with the generic closer OR an offer question. "
            f"Tail: {resp.text[-160:]!r}"
        )


# ---------------------------------------------------------------------------
# Fm5 soft conditional citation [B-P05, Brady 2026-07-14 softer-citation]
# ---------------------------------------------------------------------------


class TestFm5SoftCitation:
    @pytest.mark.acceptance
    @pytest.mark.skipif(
        not _backend_available(),
        reason=f"Backend not reachable at {API_BASE}",
    )
    def test_fm5_soft_citation_live(self, chat) -> None:
        """A named Launch-book lesson request → Brady's soft *conditional*
        citation with a REAL retrieved page: no leaked ``Book:``/``Page:``
        internal header labels, no blank page slot, and the soft
        "if you have the …" framing whenever a page is actually cited [Fm5].

        This is the wave-boundary live gate for the Fm5 deterministic
        citation-build redesign — it asserts the *property* (not exact
        wording). Skips cleanly (never errors) when no backend is up, using
        the same ``_backend_available()`` health check the conftest defines.
        """
        resp = chat.send(
            "Give me the Smekens scripted mini-lesson on topic sentences "
            "and supporting details for 3rd grade"
        )
        # Same delivered-text accessor the sibling tests assert against.
        low = resp.text.lower()

        # (1) No leaked internal citation-build header labels. The Fm5 revert
        # (ca5d0f4) failed precisely because a prompt reword leaked ``Book:`` /
        # ``Page:`` label headers into the delivered text.
        assert "book:" not in low and "page:" not in low, (
            f"Leaked Book:/Page: header label in delivered text. "
            f"Tail: {resp.text[-300:]!r}"
        )

        # (2) No blank page slot: every standalone "p." abbreviation is
        # immediately followed by a digit. The \b avoids matching a
        # word-ending "p." ("help.", "step.", "develop.").
        for m in re.finditer(r"\bp\.\s*", low):
            assert low[m.end():m.end() + 1].isdigit(), (
                f"Blank page slot leaked ('p.' with no page number). "
                f"Tail: {resp.text[-300:]!r}"
            )

        # (3) When a page IS cited, it uses Brady's soft conditional framing.
        if re.search(r"\bp\.\s*\d", low) or re.search(r"\bpage\s*\d", low):
            assert "if you have the" in low, (
                f"Page cited without the soft 'if you have the …' framing. "
                f"Tail: {resp.text[-300:]!r}"
            )
