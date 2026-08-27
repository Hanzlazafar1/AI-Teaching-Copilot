"""Retrieval acceptance tests — BRADY-ALIGNMENT-PLAN.md Section 7.1 (T01-T22).

These tests verify Brady's retrieval expectations:
- Launch books surfaced as top source for covered skills (B-R01)
- Scripted MLs used verbatim when matched (B-R02)
- Smekens triggers retrieved when skill queried (B-R03, query expansion)
- Query-type-specific priority routing (B-R04)
- Candidate-list surfacing for broad/plan queries (B-R05)

All tests are expected to FAIL before Phase 5-7 are implemented.
Property-based assertions — no brittle chunk_id matching.
"""

from __future__ import annotations

import pytest

from tests.acceptance.conftest import (
    assert_source_from_book,
    assert_top_source_matches,
)


# ---------------------------------------------------------------------------
# P0 — Launch book first / Smekens trigger retrieval
# ---------------------------------------------------------------------------


class TestRetrievalLaunchBookFirst:
    """T01-T06, T13-T18: Brady's core complaint — Launch books always first."""

    @pytest.mark.acceptance
    def test_T01_paragraphing_3rd_grade_returns_table_top(self, chat) -> None:
        """How do I teach paragraphing to 3rd graders? → table-top lesson [B-R01, B-R03]."""
        resp = chat.send("How do I teach paragraphing to 3rd graders?")
        assert_top_source_matches(resp, r"table.?top|leg")

    @pytest.mark.acceptance
    def test_T02_transitions_4th_grade(self, chat) -> None:
        """Teach 4th graders to use transitions → transitions lesson [B-R01, B-R03]."""
        resp = chat.send("Teach 4th graders to use transitions")
        assert_top_source_matches(resp, r"transition")
        assert_source_from_book(resp, "launch")

    @pytest.mark.acceptance
    def test_T03_topic_sentence_supporting_details(self, chat) -> None:
        """Topic sentence and supporting details for grade 3 → table-top/topic sentence [B-R01, B-G12]."""
        resp = chat.send("Topic sentence and supporting details for grade 3")
        assert_top_source_matches(resp, r"table.?top|leg|topic.?sentence")

    @pytest.mark.acceptance
    def test_T04_kindergarten_add_details_to_pictures(self, chat) -> None:
        """Teach kindergarteners to add details to pictures → K-2 book drawing section [B-R01]."""
        resp = chat.send("Teach kindergarteners to add details to pictures")
        assert_source_from_book(resp, "k-2")
        assert_top_source_matches(resp, r"detail|picture|draw")

    @pytest.mark.acceptance
    def test_T05_snapple_details_6th_grade(self, chat) -> None:
        """Snapple details for 6th grade → Snapple ML [B-R01]."""
        resp = chat.send("Snapple details for 6th grade")
        assert_top_source_matches(resp, r"snapple", in_first_n=3)

    @pytest.mark.acceptance
    def test_T06_slinky_test(self, chat) -> None:
        """How do I use the slinky test? → slinky/sentence length lesson [B-R03]."""
        resp = chat.send("How do I use the slinky test?")
        assert_top_source_matches(resp, r"slinky|sentence.?length", in_first_n=3)

    @pytest.mark.acceptance
    def test_T13_voice_persuasive_middle_school(self, chat) -> None:
        """Teach voice in persuasive writing for middle school → Section 10 voice [B-R04]."""
        resp = chat.send("Teach voice in persuasive writing for middle school")
        assert_top_source_matches(resp, r"voice|s10", in_first_n=3)

    @pytest.mark.acceptance
    def test_T14_k2_not_yet_writing_sentences(self, chat) -> None:
        """Writing for K-2 kids not writing sentences yet → K-2 Section 8-10 [B-R04]."""
        resp = chat.send("Writing for K-2 kids not writing sentences yet")
        assert_source_from_book(resp, "k-2")
        assert_top_source_matches(resp, r"draw|picture|label|k2-s[89]", in_first_n=3)

    @pytest.mark.acceptance
    def test_T15_dead_verbs_8th_grade(self, chat) -> None:
        """Dead verbs for 8th grade → strong verbs lesson [B-R01]."""
        resp = chat.send("Dead verbs for 8th grade")
        assert_top_source_matches(resp, r"verb", in_first_n=3)

    @pytest.mark.acceptance
    def test_T16_pizza_table_query_expansion(self, chat) -> None:
        """Pizza table for paragraph writing → table-top (trigger expansion) [B-R03]."""
        resp = chat.send("Pizza table for paragraph writing")
        assert_top_source_matches(resp, r"table.?top|leg", in_first_n=3)

    @pytest.mark.acceptance
    def test_T17_dissected_web(self, chat) -> None:
        """Dissected web for paragraph structure → dissected-web ML [B-R03]."""
        resp = chat.send("Dissected web for paragraph structure")
        assert_top_source_matches(resp, r"dissected", in_first_n=3)

    @pytest.mark.acceptance
    def test_T18_magnify_close_up_K(self, chat) -> None:
        """Magnify close-up details for K → K-2 Section 8 drawing [B-R01]."""
        resp = chat.send("Magnify close-up details for K")
        assert_source_from_book(resp, "k-2")
        assert_top_source_matches(resp, r"magnif|close.?up", in_first_n=3)


# ---------------------------------------------------------------------------
# P0 — Query-type routing
# ---------------------------------------------------------------------------


class TestQueryTypeRouting:
    """T07-T12, T19-T22: Different query types get different retrieval strategies."""

    @pytest.mark.acceptance
    def test_T07_persuasive_introductions_5th_grade(self, chat) -> None:
        """Teach persuasive introductions to 5th graders → Section 9 persuasive intros [B-R04]."""
        resp = chat.send("Teach persuasive introductions to 5th graders")
        assert_top_source_matches(resp, r"persuas.*introduct|intro.*persuas", in_first_n=3)

    @pytest.mark.acceptance
    def test_T08_plan_persuasive_unit_4th_grade(self, chat) -> None:
        """Plan a persuasive unit for 4th grade → PIE doc / priority_skill_list [B-R04]."""
        resp = chat.send("Plan a persuasive unit for 4th grade")
        # Expect priority_skill_list content_type OR PIE doc source
        pattern = r"priority_skill_list|essential.?skills|pie|persuasive"
        assert_top_source_matches(resp, pattern, in_first_n=3)

    @pytest.mark.acceptance
    def test_T09_workshop_routines(self, chat) -> None:
        """How do I set up writers workshop routines? → Launch book Ch 1-7 [B-R04]."""
        resp = chat.send("How do I set up writers workshop routines?")
        # Chapters 1-7 covered by section names like s1-s7
        assert_top_source_matches(resp, r"lww312-s[1-7]|k2-s[1-7]|workshop|setting", in_first_n=3)

    @pytest.mark.acceptance
    def test_T10_introduce_writers_notebooks(self, chat) -> None:
        """How do I introduce writer's notebooks? → Section 3 [B-R04]."""
        resp = chat.send("How do I introduce writer's notebooks?")
        assert_top_source_matches(resp, r"s3|notebook|creating", in_first_n=3)

    @pytest.mark.acceptance
    def test_T11_authors_chair(self, chat) -> None:
        """How do I run author's chair? → Section 2 setting expectations [B-R04]."""
        resp = chat.send("How do I run author's chair?")
        assert_top_source_matches(resp, r"s2|author|sharing", in_first_n=3)

    @pytest.mark.acceptance
    def test_T12_motivate_reluctant_writers(self, chat) -> None:
        """How do I motivate reluctant writers? → Section 4 [B-R04]."""
        resp = chat.send("How do I motivate reluctant writers?")
        assert_top_source_matches(resp, r"s4|motivat", in_first_n=3)

    @pytest.mark.acceptance
    def test_T19_scripted_ml_grade3_persuasive(self, chat) -> None:
        """Give me a scripted ML for grade 3 persuasive opinion → ML Library match or scripted chunks [B-R02]."""
        resp = chat.send("Give me a scripted ML for grade 3 persuasive opinion writing")
        # Should return a match from library or scripted content (after Phase 14)
        # Property: response is a MiniLesson OR sources include scripted content
        has_scripted = any(
            "script" in (s.get("content_type") or "").lower()
            or "library" in (s.get("content_type") or "").lower()
            or s.get("chunk_id", "").startswith("lib-")
            for s in resp.sources
        )
        assert resp.is_lesson or has_scripted, (
            f"Expected scripted ML or library match. "
            f"is_lesson={resp.is_lesson}, sources={[s.get('chunk_id') for s in resp.sources[:3]]}"
        )

    @pytest.mark.acceptance
    def test_T20_four_essential_informative(self, chat) -> None:
        """What are the four essential skills for informative writing? → Ep 3 or Essential Skills [B-R04]."""
        resp = chat.send("What are the four essential skills for informative writing?")
        assert_top_source_matches(resp, r"ep3|essential.?skills|four.?essential", in_first_n=3)

    @pytest.mark.acceptance
    def test_T21_done_list_strategy(self, chat) -> None:
        """Help with done list strategy → Section 4 ML #1 [B-R04]."""
        resp = chat.send("Help with the done list strategy")
        assert_top_source_matches(resp, r"done.?list|s4", in_first_n=3)

    @pytest.mark.acceptance
    def test_T22_narrative_introductions_grade_9(self, chat) -> None:
        """Teach narrative introductions for grade 9 → Section 9 ML#17 or E-tagged for grade 9 [B-R04]."""
        resp = chat.send("Teach narrative introductions for grade 9")
        assert_top_source_matches(resp, r"narrative.*intro|intro.*narrative|s9-ml17", in_first_n=3)
