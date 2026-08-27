"""Session-memory acceptance tests — BRADY-ALIGNMENT-PLAN.md Section 7.3 (TS01-TS19).

Multi-turn scenarios that exercise session-aware state:
- Active skill / grade / mode locked across turns [B-S01, B-S02]
- Previous outputs referenceable ("where's that organizer?", "what page?") [B-S03]
- Think-aloud reuse ("use what you just wrote") [B-S04]
- Skill list pickup (ordinal + fuzzy title) [B-S05]
- Library verbatim flow (VERBATIM / ASK_USER / SURFACE_LIST / decline)
- Topic shift confirmation [Mode 5]
- Correction flow [Mode 6]
- B-F03 one-time SCRIPTED_ML confirmation

All tests expected to FAIL before Phase 12 is implemented.
"""

from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# TS01-TS07: Grade / skill / context persistence
# ---------------------------------------------------------------------------


class TestContextPersistence:
    @pytest.mark.acceptance
    def test_TS01_grade_carried_into_scripted_ml(self, chat) -> None:
        """Turn 1 sets grade=5 and skill=transitions; Turn 2 requesting scripted ML must not re-ask grade [B-S01, B-S02]."""
        chat.send("I teach 5th grade and want a lesson on transitions")
        resp2 = chat.send("Can you put that in a scripted ML?")
        text2 = resp2.text.lower()
        # Should NOT ask for grade again
        assert "what grade" not in text2, (
            f"Turn 2 re-asked grade despite grade=5 being established. Response: {text2[:300]!r}"
        )
        # Should be a lesson or at least about 5th grade transitions
        if resp2.is_lesson:
            assert "5" in (resp2.lesson.get("grade_level") or "")

    @pytest.mark.acceptance
    def test_TS06_grade_never_re_asked(self, chat) -> None:
        """Across 5 turns with grade=4 established, grade never re-asked [B-S01]."""
        chat.send("I teach 4th grade. What is the slinky test?")
        chat.send("Tell me about the pizza table strategy")
        chat.send("How do I help kids with transitions?")
        resp4 = chat.send("Give me a scripted ML on voice")
        text4 = resp4.text.lower()
        assert "what grade" not in text4, (
            f"Turn 4 re-asked grade after grade=4 established at turn 1. {text4[:300]!r}"
        )

    @pytest.mark.acceptance
    def test_TS07_coaching_chain_then_lesson(self, chat) -> None:
        """Coaching chain about 'voice' then 'give me a lesson on this' uses active.skill [B-S02, B-S05]."""
        chat.send("I teach 4th grade. How do I help students develop voice?")
        chat.send("What are some voice strategies for younger writers?")
        chat.send("Tell me more about Smekens' voice techniques")
        resp = chat.send("Now create a lesson on this")
        text = resp.text.lower()
        # Must not ask for skill — should know it's voice
        assert "what skill" not in text and "what specific skill" not in text, (
            f"Turn 4 re-asked skill after 3 turns about voice. {text[:300]!r}"
        )
        # Output should be about voice (not a random skill)
        if resp.is_lesson:
            skill_focus = (resp.lesson.get("skill_focus") or "").lower()
            assert "voice" in skill_focus, (
                f"Lesson skill_focus should mention 'voice'. Got: {skill_focus!r}"
            )


# ---------------------------------------------------------------------------
# TS02, TS08: State references (organizer, book page)
# ---------------------------------------------------------------------------


class TestPreviousOutputReferences:
    @pytest.mark.acceptance
    def test_TS02_where_is_that_organizer(self, chat) -> None:
        """After a response mentions an organizer, 'where's that organizer?' uses active.last_organizer_mentioned [B-S03]."""
        chat.send("How do I teach paragraphing for 3rd graders?")
        resp2 = chat.send("Where can I get that organizer?")
        text2 = resp2.text.lower()
        # Must not ask 'what organizer?' — should remember
        assert "what organizer" not in text2 and "what specific graphic" not in text2, (
            f"Turn 2 forgot the organizer mentioned in Turn 1. {text2[:300]!r}"
        )
        # Should mention book page and digital resources
        assert re.search(r"page\s*\d+", text2) or "digital resource" in text2, (
            f"Expected book page or digital resources reference. {text2[:300]!r}"
        )

    @pytest.mark.acceptance
    def test_TS08_what_page_is_this_on(self, chat) -> None:
        """After a lesson is discussed, 'what page?' points to the page OR stays
        honestly silent — never a guessed/wrong page [B-S03, B-P05].

        Brady's rule is "better to stay silent than lie": this deictic follow-up
        is referent-less, so retrieval re-runs on it and returns generic chunks —
        the lesson actually asked about may be absent. Emitting a confident page
        from those chunks is the C2 defect (fix 8 part 1). So this accepts EITHER
        a numeric page reference OR an honest book/digital-resources pointer —
        mirroring TS02 above — while still requiring an on-topic response (it must
        not always-pass)."""
        chat.send("Give me a scripted mini-lesson on Snapple details for 6th grade")
        resp2 = chat.send("What page is this lesson on?")
        text2 = resp2.text.lower()
        # A page reference OR an honest pointer to the Launch book / its digital
        # resources (silence over a guessed page). Part-1 silence produces varied
        # honest pointers — some name "digital resources", some just point to the
        # named Launch book / a section — so accept any recognizable book pointer,
        # not only the literal words "digital resource" (measured live: the
        # digital-resources phrasing appears ~2/3 of runs, the Launch-book pointer
        # in all of them). Still not always-pass: a bare non-answer with no page
        # and no book reference fails.
        assert (
            re.search(r"page\s*\d+", text2)
            or any(s in text2 for s in ("digital resource", "launch", "the book"))
        ), (
            f"Expected a page OR an honest pointer to the Launch book / its digital "
            f"resources (silence over a guessed page). {text2[:300]!r}"
        )


# ---------------------------------------------------------------------------
# TS03: Perfect think-aloud reuse
# ---------------------------------------------------------------------------


class TestThinkAloudReuse:
    @pytest.mark.acceptance
    def test_TS03_use_what_you_just_wrote(self, chat) -> None:
        """After a think-aloud, 'put that in a 4-step ML' uses the think-aloud verbatim in Step 2B [B-S04]."""
        chat.send(
            "Give me a think-aloud for choosing a transition between "
            "'My mom is having surgery' and 'She is very anxious'"
        )
        tap = chat.last
        # Extract a distinctive fragment from the think-aloud response
        ta_text = tap.text
        # Pick a 30-char distinctive substring from the middle
        mid = len(ta_text) // 2
        excerpt = ta_text[mid - 30:mid + 30].strip()

        resp2 = chat.send("Now put that think-aloud into a 4-step ML for grade 4")
        assert resp2.is_lesson, "Turn 2 should produce a MiniLesson"
        s2b = resp2.lesson.get("step_2b_show") or ""
        # Distinctive fragment from Turn 1's think-aloud should appear in Step 2B
        assert any(
            phrase in s2b
            for phrase in [excerpt[-20:], "my mom is having surgery", "she is very anxious"]
        ), (
            f"Step 2B must reuse the Turn 1 think-aloud. "
            f"Turn 1 excerpt: {excerpt!r}. Step 2B: {s2b[:400]!r}"
        )


# ---------------------------------------------------------------------------
# TS04, TS12, TS15: Skill list pickup
# ---------------------------------------------------------------------------


class TestSkillListPickup:
    @pytest.mark.acceptance
    def test_TS04_ordinal_pickup_from_plan_unit(self, chat) -> None:
        """After PLAN_UNIT lists N skills, 'lesson on number 4' picks skill at position 4 [B-S05]."""
        chat.send("Plan a persuasive writing unit for 4th grade")
        resp2 = chat.send("Give me a lesson on number 4")
        # Response should be a lesson (or library offer) about a specific skill
        text2 = resp2.text.lower()
        assert "what skill" not in text2, (
            f"Turn 2 must map 'number 4' to an offered skill, not ask what skill. {text2[:300]!r}"
        )

    @pytest.mark.acceptance
    def test_TS12_fuzzy_title_pickup(self, chat) -> None:
        """After a skill list, 'lesson on Snapple details' matches by fuzzy title [B-S05]."""
        chat.send("What lessons are there for 6th grade informative writing?")
        resp2 = chat.send("Give me a lesson on Snapple details")
        text2 = resp2.text.lower()
        assert "what skill" not in text2, (
            f"Turn 2 must map 'Snapple details' to a title from the list. {text2[:300]!r}"
        )
        # Lesson, if produced, should be about Snapple
        if resp2.is_lesson:
            skill_focus = (resp2.lesson.get("skill_focus") or "").lower()
            assert "snapple" in skill_focus, (
                f"skill_focus must contain 'Snapple'. Got: {skill_focus!r}"
            )

    @pytest.mark.acceptance
    def test_TS15_how_to_teach_sub_skill_pickup(self, chat) -> None:
        """After HOW_TO_TEACH offered 5 sub-skills, 'lesson on the third one' generates for sub-skill at position 3 [B-S05]."""
        chat.send("How do I teach paragraph writing to 3rd graders?")
        resp2 = chat.send("Give me a lesson on the third one")
        text2 = resp2.text.lower()
        assert "what skill" not in text2 and "what aspect" not in text2, (
            f"Turn 2 must pickup from HOW_TO_TEACH sub-skills. {text2[:300]!r}"
        )


# ---------------------------------------------------------------------------
# TS05: Skill doesn't switch mid-conversation
# ---------------------------------------------------------------------------


class TestSkillLocking:
    @pytest.mark.acceptance
    def test_TS05_how_to_teach_then_scripted_same_skill(self, chat) -> None:
        """HOW_TO_TEACH voice → 'scripted ML' → generated ML is about voice, not a different skill [B-S02]."""
        chat.send("How do I teach voice to 3rd graders?")
        resp2 = chat.send("Give me a scripted ML")
        if resp2.is_lesson:
            skill_focus = (resp2.lesson.get("skill_focus") or "").lower()
            assert "voice" in skill_focus, (
                f"SCRIPTED_ML must stay on 'voice' skill. skill_focus: {skill_focus!r}"
            )


# ---------------------------------------------------------------------------
# TS09: Active state filters retrieval
# ---------------------------------------------------------------------------


class TestActiveStateFiltersRetrieval:
    @pytest.mark.acceptance
    def test_TS09_example_uses_active_skill(self, chat) -> None:
        """Active skill=transitions/grade=4; 'give me an example' retrieves transition examples, not generic [B-S02 retrieval side]."""
        chat.send("I teach 4th grade. Tell me about transitions.")
        resp2 = chat.send("Give me an example")
        text2 = resp2.text.lower()
        # Example should be about transitions (word present or related)
        assert any(
            term in text2
            for term in ["transition", "however", "because", "therefore", "furthermore", "linking"]
        ), (
            f"Example must relate to active skill 'transitions'. Got: {text2[:500]!r}"
        )


# ---------------------------------------------------------------------------
# TS10: Topic shift confirmation (Mode 5)
# ---------------------------------------------------------------------------


class TestTopicShiftConfirmation:
    @pytest.mark.acceptance
    def test_TS10_topic_shift_requires_confirmation(self, chat) -> None:
        """Active=transitions/grade 4 → 'now do voice for grade 6' → system asks to confirm [Mode 5]."""
        chat.send("Give me a lesson on transitions for grade 4 informational writing")
        resp2 = chat.send("Now do voice for grade 6")
        text2 = resp2.text.lower()
        # System should ask to confirm the topic switch, not silently proceed
        confirmation_markers = [
            "switch", "change", "confirm", "correct?", "should i", "do you want",
        ]
        assert any(m in text2 for m in confirmation_markers), (
            f"Topic shift should trigger a confirmation prompt. "
            f"Got: {text2[:400]!r}"
        )


# ---------------------------------------------------------------------------
# TS11: Refinement of verbatim ML
# ---------------------------------------------------------------------------


class TestRefinementOfVerbatim:
    @pytest.mark.acceptance
    def test_TS11_refine_library_verbatim(self, chat) -> None:
        """Library verbatim ML returned → 'make it shorter' → shortened version (refinement of last_response_text)."""
        resp1 = chat.send("Give me a scripted ML on Snapple details for grade 6")
        if not resp1.is_lesson and "would you like" not in resp1.text.lower():
            pytest.skip("Library didn't match; refinement test not applicable")
        resp2 = chat.send("Make it shorter")
        # Turn 2 should be a response (not an error)
        assert resp2.text, "Turn 2 must produce a response"
        assert resp2.quality != "error", f"Refinement returned error: {resp2.text[:200]}"


# ---------------------------------------------------------------------------
# TS13: Library offer declined
# ---------------------------------------------------------------------------


class TestLibraryDecline:
    @pytest.mark.acceptance
    def test_TS13_decline_library_offer(self, chat) -> None:
        """Library ASK_USER → 'no, generate one' → system runs main retrieval + generation."""
        resp1 = chat.send(
            "Give me a scripted ML on Snapple details for grade 6"
        )
        # If system gave verbatim automatically, test not applicable
        if resp1.is_lesson:
            pytest.skip("Library returned VERBATIM_AUTO, no offer to decline")
        text1 = resp1.text.lower()
        if "verbatim" not in text1 and "would you like" not in text1:
            pytest.skip("System did not offer — nothing to decline")

        resp2 = chat.send("No, please generate one for me")
        # Turn 2 should produce a fresh lesson (not repeat the offer)
        assert resp2.text, "Turn 2 must produce a response"
        assert "verbatim" not in resp2.text.lower()[:500] or resp2.is_lesson


# ---------------------------------------------------------------------------
# TS16: Broad SCRIPTED_ML → SURFACE_LIST
# ---------------------------------------------------------------------------


class TestBroadQuerySurfaceList:
    @pytest.mark.acceptance
    def test_TS16_broad_query_offers_list(self, chat) -> None:
        """'Give me a persuasive lesson for 5th grade' (broad) → system offers
        candidates OR asks the teacher to narrow [B-R05].

        ⚠️ This test failed for months on a KEYWORD MISMATCH WITH THE APP'S OWN
        CORRECT WORDING — it asks "Which specific writing skill did you have in
        mind?", which none of the terms below used to match. waves.md files
        TS16 under "test-too-strict → relax the test"; the recorded follow-ups
        proposed changing the APP to emit one of these phrases, which would
        have cemented a drift instead.

        The drift is traceable to ONE vendor-doc entry. FEEDBACK-ISSUES.md
        B-R05 quotes Brady correctly — "look at the P lessons. What are the P
        lessons? Maybe suggest those." — and its "Expected behavior" scopes him
        correctly to "'plan a unit' / 'what are the skills for X' queries".
        Then its own "Status" line widens that to "Broad queries like 'Give me
        a persuasive lesson for 5th grade'", and this test inherited the wider
        scope. The primary was never wrong; the row beneath it drifted.

        Asking which skill IS the right answer to a lesson request that names
        no skill — the alternative is inventing one, which is Brady's original
        complaint. So the terms match what the app correctly says.
        """
        resp = chat.send("Give me a persuasive lesson for 5th grade")
        text = resp.text.lower()
        # Either: (a) library surface_list offer, OR (b) skill list, OR (c) asks for specific skill
        has_list = bool(re.search(r"^\s*\d+\.", resp.text, re.MULTILINE))
        asks_specific = any(
            term in text
            for term in [
                "which one", "what specific", "which skill", "which lesson",
                # the app's own clarify wording (handlers/__init__.py)
                "writing skill",
            ]
        )
        assert has_list or asks_specific, (
            f"Broad query should offer candidates or ask to narrow. Got: {text[:400]!r}"
        )


# ---------------------------------------------------------------------------
# TS17: Correction flow (Mode 6)
# ---------------------------------------------------------------------------


class TestCorrectionFlow:
    @pytest.mark.acceptance
    def test_TS17_correction_updates_skill_silently(self, chat) -> None:
        """User says 'That's not what I asked for, I wanted X' → Mode 6 silently updates skill, no confirmation."""
        chat.send("Give me a scripted ML on details for 3rd grade")
        resp2 = chat.send(
            "That's not what I asked for. I wanted topic sentence and supporting details."
        )
        # Should NOT ask for confirmation (not Mode 5), should proceed with corrected skill
        text2 = resp2.text.lower()
        # Response should either be a lesson on topic sentence+details, OR reference them
        if resp2.is_lesson:
            skill_focus = (resp2.lesson.get("skill_focus") or "").lower()
            assert "topic sentence" in skill_focus, (
                f"After correction, skill_focus must reflect corrected skill. Got: {skill_focus!r}"
            )
        else:
            # Or at minimum mention the corrected terms
            assert "topic sentence" in text2, (
                f"Correction not applied. Got: {text2[:400]!r}"
            )


# ---------------------------------------------------------------------------
# TS18, TS19: B-F03 one-time SCRIPTED_ML confirmation
# ---------------------------------------------------------------------------


class TestScriptedMLConfirmation:
    @pytest.mark.acceptance
    def test_TS18_first_scripted_ml_confirmation(self, chat) -> None:
        """First SCRIPTED_ML in session (no library match) triggers B-F03 confirmation prompt."""
        resp = chat.send(
            "Give me a scripted ML on transitions for grade 4 informational"
        )
        if resp.is_lesson:
            pytest.skip("Library matched — confirmation is skipped by design")
        text = resp.text.lower()
        confirmation_markers = [
            "correct?", "is that right", "confirm", "so you want",
        ]
        # Should either be a library offer OR the B-F03 confirmation
        has_confirmation = any(m in text for m in confirmation_markers)
        has_library_offer = "verbatim" in text
        assert has_confirmation or has_library_offer, (
            f"First SCRIPTED_ML should trigger a confirmation or library offer. "
            f"Got: {text[:400]!r}"
        )

    @pytest.mark.acceptance
    def test_TS19_subsequent_scripted_ml_no_confirmation(self, chat) -> None:
        """After one SCRIPTED_ML is confirmed, subsequent SCRIPTED_MLs in session skip B-F03."""
        # Turn 1: trigger confirmation
        chat.send("Give me a scripted ML on transitions for grade 4")
        # Turn 2: confirm if needed
        if "correct?" in chat.last.text.lower() or "verbatim" in chat.last.text.lower():
            chat.send("yes")
        # Turn 3: another SCRIPTED_ML should NOT confirm again
        resp3 = chat.send("Now give me a scripted ML on voice for grade 4")
        text3 = resp3.text.lower()
        # Should not ask confirmation again
        assert "correct?" not in text3[-300:] or resp3.is_lesson, (
            f"Subsequent SCRIPTED_ML triggered another confirmation. "
            f"Got tail: {text3[-300:]!r}"
        )


# ---------------------------------------------------------------------------
# TS14: Coaching chain → lesson uses active.skill (covered also by TS07)
# ---------------------------------------------------------------------------

# TS14 is equivalent to TS07 above — kept as a separate class for traceability
class TestCoachingChainToLesson:
    @pytest.mark.acceptance
    def test_TS14_coaching_chain_active_skill_captured(self, chat) -> None:
        """Extended coaching chain about 'voice' → asking for lesson uses voice without re-asking [B-S02]."""
        chat.send("Tell me about Smekens' approach to voice in writing")
        chat.send("What strategies help 3rd graders develop voice?")
        chat.send("How do Smekens think-alouds demonstrate voice?")
        resp = chat.send("OK, give me a lesson on this for my 3rd graders")
        text = resp.text.lower()
        assert "what skill" not in text and "what specific skill" not in text, (
            f"Must not re-ask skill after coaching chain about voice. Got: {text[:300]!r}"
        )
        if resp.is_lesson:
            skill_focus = (resp.lesson.get("skill_focus") or "").lower()
            assert "voice" in skill_focus, (
                f"skill_focus must reflect active.skill='voice'. Got: {skill_focus!r}"
            )
