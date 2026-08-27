"""Unit tests for Phase 6 priority re-ranking (Section 13 of plan).

Each test fabricates a RetrievedChunk with the specific metadata combination
that should trigger one boost rule, then asserts the expected multiplier.
"""

from __future__ import annotations

import pytest

from retrieval.reranker import (
    NEUTRAL,
    _source_tier,
    grade_to_band,
    priority_boost,
    rerank,
)
from retrieval.search import RetrievedChunk


def _chunk(
    chunk_id: str = "test-chunk",
    source_document: str = "",
    book_name: str | None = None,
    chapter_number: int | None = None,
    ml_number: int | None = None,
    skill_title: str = "",
    pie_tags_by_band: dict | None = None,
    page_number: int | None = None,
    writing_mode: str = "",
    is_scripted_lesson: bool = False,
    score: float = 1.0,
    content_type: str = "",
    grade_level: str = "",
    lesson_trigger: list | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_document=source_document,
        content_type=content_type,
        content="",
        grade_level=grade_level,
        writing_trait="",
        writing_mode=writing_mode,
        strategy_name="",
        tier=2,
        step="",
        score=score,
        book_name=book_name,
        chapter_number=chapter_number,
        ml_number=ml_number,
        skill_title=skill_title,
        pie_tags_by_band=pie_tags_by_band or {},
        page_number=page_number,
        is_scripted_lesson=is_scripted_lesson,
        lesson_trigger=list(lesson_trigger or []),
    )


# ---------------------------------------------------------------------------
# grade_to_band mapping
# ---------------------------------------------------------------------------


class TestGradeToBand:
    @pytest.mark.parametrize("grade,expected", [
        ("K", "K-2"),
        ("1", "K-2"),
        ("2", "K-2"),
        ("3", "3-5"),
        ("4", "3-5"),
        ("5", "3-5"),
        ("6", "6-8"),
        ("7", "6-8"),
        ("8", "6-8"),
        ("9", "9-12"),
        ("10", "9-12"),
        ("11", "9-12"),
        ("12", "9-12"),
    ])
    def test_single_grade_maps_to_band(self, grade, expected):
        assert grade_to_band(grade) == expected

    def test_band_input_returned_as_is(self):
        assert grade_to_band("3-5") == "3-5"
        assert grade_to_band("K-2") == "K-2"

    def test_none_returns_none(self):
        assert grade_to_band(None) is None

    def test_unrecognized_grade_returns_none(self):
        assert grade_to_band("13") is None
        assert grade_to_band("pre-K") is None


# ---------------------------------------------------------------------------
# SCRIPTED_ML / HOW_TO_TEACH boosts
# ---------------------------------------------------------------------------


class TestBoostScriptedOrHowTo:
    def test_launch_book_with_pacing_pie_tag_wins(self):
        # Launch 3-12 chunk with pie_tags_by_band[3-5] = ["P"] — top priority for grade 4 persuasive
        chunk = _chunk(
            book_name="Teal",
            chapter_number=8,
            pie_tags_by_band={"3-5": ["P"], "6-8": ["P", "I"]},
            is_scripted_lesson=True,
        )
        assert priority_boost(chunk, "SCRIPTED_ML", user_grade="4", writing_mode="Persuade") == 2.0

    def test_launch_book_no_pacing_tag_for_band(self):
        # Launch 3-12 chunk with pacing tag for 6-8 only — for grade 4 it drops out of the 2.0 tier
        chunk = _chunk(
            book_name="Teal",
            chapter_number=8,
            pie_tags_by_band={"6-8": ["P"]},
            is_scripted_lesson=True,
            writing_mode="Persuade",
        )
        # Scripted ML with matching mode = 1.5 tier
        assert priority_boost(chunk, "SCRIPTED_ML", user_grade="4", writing_mode="Persuade") == 1.5

    def test_launch_book_chapter_1_to_7_deprioritized(self):
        # Workshop-management content should be pushed DOWN for SCRIPTED_ML questions
        chunk = _chunk(
            book_name="Teal",
            chapter_number=3,
            pie_tags_by_band={},
        )
        assert priority_boost(chunk, "SCRIPTED_ML", user_grade="4", writing_mode="Persuade") == 0.7

    def test_library_source_chunk_with_pie_tag(self):
        """Library-source chunks have their chunk_id in _LIBRARY_SOURCE_CHUNK_IDS."""
        # Use a real library source chunk id
        chunk = _chunk(
            chunk_id="lww312-s8-ml05-table-top-leg-sentences",
            book_name="Teal",
            chapter_number=8,
            pie_tags_by_band={"3-5": ["P"]},
            is_scripted_lesson=True,
        )
        # Both rules match (Launch+pie_tag AND library_source+pie_tag) — Launch+pie wins at 2.0
        assert priority_boost(chunk, "SCRIPTED_ML", user_grade="4", writing_mode="Persuade") == 2.0

    def test_essential_skills_pie_moderately_boosted(self):
        """Essential Skills PIE doc = the 'skill 1/2' priority-skill sequences.
        Distinct from 'essential 2 explicit instruction' which is core methodology
        (that's 1.5 only under COACHING_GENERAL)."""
        chunk = _chunk(source_document="skill 1. day 1.pdf")
        assert priority_boost(chunk, "SCRIPTED_ML", user_grade="4", writing_mode="Persuade") == 1.3

    def test_unrelated_source_neutral(self):
        chunk = _chunk(source_document="essential 2 explicit instruction.pdf")
        # Not a Launch book, not Essential Skills PIE, no tags — neutral fallback
        assert priority_boost(chunk, "SCRIPTED_ML", user_grade="4", writing_mode="Persuade") == 1.0

    def test_how_to_teach_uses_same_table(self):
        chunk = _chunk(
            book_name="Teal",
            chapter_number=8,
            pie_tags_by_band={"3-5": ["P"]},
            is_scripted_lesson=True,
        )
        assert priority_boost(chunk, "HOW_TO_TEACH", user_grade="4", writing_mode="Persuade") == 2.0

    def test_unknown_mode_drops_mode_specific_rules(self):
        # writing_mode=None means no pie-tag match, no 1.5 ML tier
        chunk = _chunk(
            book_name="Teal",
            chapter_number=8,
            pie_tags_by_band={"3-5": ["P"]},
            is_scripted_lesson=True,
        )
        # No mode → chapter 8 is not 1-7, so no deprioritize; fallback 1.0
        assert priority_boost(chunk, "SCRIPTED_ML", user_grade="4", writing_mode=None) == 1.0


# ---------------------------------------------------------------------------
# PLAN_UNIT boosts
# ---------------------------------------------------------------------------


class TestBoostPlanUnit:
    def test_essential_skills_pie_is_top(self):
        chunk = _chunk(source_document="skill 1. day 1.pdf")
        assert priority_boost(chunk, "PLAN_UNIT", user_grade="4", writing_mode="Inform") == 2.5

    def test_launch_book_pacing_page(self):
        chunk = _chunk(
            book_name="Teal",
            chapter_number=8,
            page_number=64,
        )
        assert priority_boost(chunk, "PLAN_UNIT", user_grade="4", writing_mode="Inform") == 1.8

    def test_launch_book_non_pacing(self):
        chunk = _chunk(book_name="Teal", chapter_number=8, page_number=None)
        assert priority_boost(chunk, "PLAN_UNIT", user_grade="4", writing_mode="Inform") == 1.0

    def test_episode_script_deprioritized(self):
        chunk = _chunk(source_document="ep 3 sec script.pdf")
        assert priority_boost(chunk, "PLAN_UNIT", user_grade="4", writing_mode="Inform") == 0.5

    def test_other_neutral(self):
        chunk = _chunk(source_document="some-other-source.pdf")
        assert priority_boost(chunk, "PLAN_UNIT", user_grade="4", writing_mode="Inform") == 1.0


# ---------------------------------------------------------------------------
# MANAGEMENT boosts
# ---------------------------------------------------------------------------


class TestBoostManagement:
    def test_launch_book_chapter_1_to_5_top(self):
        """Workshop-setup chapters — the authoritative source for management
        questions. Brady scopes this himself, in both primaries and twice:
        "When 'routines, management, start up, writer's workshop, writer
        habits, expectations, procedures' are the focus, then Co-Pilot must
        pull from Sections 1-5 in the Launch books" (feedback-docx.txt:143,
        feedback-pdf.txt:211) and "PART 1 of the Launch books" (docx:138).

        This asserted ch 1-7 until 2026-07-17. NO primary says 1-7 — the range
        was ours, and this test defended it while sections 6-7 (define-trait,
        mentor texts, rubric building) were boosted 2.0 for routines questions.
        Measured live: a "how do I set up writing workshop routines" follow-up
        was topped by lww312-s6-ml1-define-trait-visually-verbally.
        """
        for ch in [1, 2, 3, 4, 5]:
            chunk = _chunk(book_name="Teal", chapter_number=ch)
            assert priority_boost(chunk, "MANAGEMENT", None, None) == 2.0

    def test_launch_book_chapter_6_to_13_heavily_deprioritized(self):
        """Everything above Brady's Part 1 is wrong-audience for a management
        question — 6-7 are trait instruction and assessment, 8-13 are the
        skill mini-lessons."""
        for ch in [6, 7, 8, 9, 10, 11, 12, 13]:
            chunk = _chunk(book_name="Teal", chapter_number=ch)
            assert priority_boost(chunk, "MANAGEMENT", None, None) == 0.4

    def test_twpdms_ep11_boosted(self):
        chunk = _chunk(source_document="ep 11 k-12 script.pdf")
        assert priority_boost(chunk, "MANAGEMENT", None, None) == 1.3

    def test_ep1_k12_boosted(self):
        chunk = _chunk(source_document="ep 1 k-12 script.pdf")
        assert priority_boost(chunk, "MANAGEMENT", None, None) == 1.2

    def test_other_neutral(self):
        chunk = _chunk(source_document="some-other.pdf")
        assert priority_boost(chunk, "MANAGEMENT", None, None) == 1.0


# ---------------------------------------------------------------------------
# EARLY_WRITER boosts
# ---------------------------------------------------------------------------


class TestBoostEarlyWriter:
    def test_k2_section_8_to_10_top(self):
        for ch in [8, 9, 10]:
            chunk = _chunk(book_name="K-2", chapter_number=ch)
            assert priority_boost(chunk, "EARLY_WRITER", user_grade="K", writing_mode=None) == 2.0

    def test_k2_drawing_title(self):
        chunk = _chunk(
            book_name="K-2",
            chapter_number=12,  # outside 8-10
            skill_title="Add drawing details",
        )
        assert priority_boost(chunk, "EARLY_WRITER", user_grade="K", writing_mode=None) == 1.8

    def test_k2_label_title(self):
        chunk = _chunk(
            book_name="K-2",
            chapter_number=12,
            skill_title="Write labels for pictures",
        )
        assert priority_boost(chunk, "EARLY_WRITER", user_grade="K", writing_mode=None) == 1.8

    def test_k2_sentence_era_chapters_deprioritized(self):
        """K-2 chapters 11+ (sentence-era + fine-tuning) are the WRONG audience
        for pre-sentence writers — they get a 0.4 deprioritize so a query like
        'not writing sentences yet' doesn't accidentally match 'Writing Sentences'."""
        for ch in (11, 12, 13):
            chunk = _chunk(book_name="K-2", chapter_number=ch, skill_title="Mini-lesson on X")
            assert priority_boost(chunk, "EARLY_WRITER", user_grade="K", writing_mode=None) == 0.4

    def test_k2_pre_sentence_chapters_kept_neutral(self):
        """K-2 chapters 1-7 (foundations/management) stay at 1.2 — they're
        not the primary signal but not actively wrong for early writers."""
        for ch in (1, 3, 5, 7):
            chunk = _chunk(book_name="K-2", chapter_number=ch, skill_title="Mini-lesson on X")
            assert priority_boost(chunk, "EARLY_WRITER", user_grade="K", writing_mode=None) == 1.2

    def test_3_12_book_heavily_deprioritized(self):
        """3-12 book is almost never relevant for early writers."""
        chunk = _chunk(
            book_name="Teal",
            source_document="launching the writers workshop 3-12.pdf",
        )
        assert priority_boost(chunk, "EARLY_WRITER", user_grade="K", writing_mode=None) == 0.3

    def test_non_launch_book_neutral(self):
        chunk = _chunk(source_document="some-other.pdf")
        assert priority_boost(chunk, "EARLY_WRITER", user_grade="K", writing_mode=None) == 1.0


# ---------------------------------------------------------------------------
# COACHING_GENERAL boosts
# ---------------------------------------------------------------------------


class TestBoostCoachingGeneral:
    def test_launch_book_any_chunk_is_top(self):
        """Brady: 'always, always, always' start with Launch book for coaching."""
        for book, ch in [("Teal", 3), ("Teal", 10), ("K-2", 5), ("K-2", 9)]:
            chunk = _chunk(book_name=book, chapter_number=ch)
            assert priority_boost(chunk, "COACHING_GENERAL", None, None) == 2.0

    def test_core_methodology_boosted(self):
        for src in [
            "essential 2 explicit instruction.pdf",
            "master the 4-step mini-lesson.pdf",
            "think-aloud scripts.pdf",
        ]:
            chunk = _chunk(source_document=src)
            assert priority_boost(chunk, "COACHING_GENERAL", None, None) == 1.5

    def test_episode_scripts_boosted(self):
        chunk = _chunk(source_document="ep 3 sec script.pdf")
        assert priority_boost(chunk, "COACHING_GENERAL", None, None) == 1.3

    def test_training_transcripts_slight_boost(self):
        chunk = _chunk(source_document="writing lessons redefined as mini-lessons.pdf")
        assert priority_boost(chunk, "COACHING_GENERAL", None, None) == 1.1

    def test_other_neutral(self):
        chunk = _chunk(source_document="unknown.pdf")
        assert priority_boost(chunk, "COACHING_GENERAL", None, None) == 1.0


# ---------------------------------------------------------------------------
# DEFAULT / TRIGGER_SPECIFIC dispatch
# ---------------------------------------------------------------------------


class TestDefaultFallback:
    def test_default_uses_scripted_table(self):
        chunk = _chunk(
            book_name="Teal",
            chapter_number=8,
            pie_tags_by_band={"3-5": ["P"]},
            is_scripted_lesson=True,
        )
        # DEFAULT and TRIGGER_SPECIFIC should behave like SCRIPTED_ML
        assert priority_boost(chunk, "DEFAULT", user_grade="4", writing_mode="Persuade") == 2.0
        assert priority_boost(chunk, "TRIGGER_SPECIFIC", user_grade="4", writing_mode="Persuade") == 2.0


# ---------------------------------------------------------------------------
# rerank() ordering + score mutation
# ---------------------------------------------------------------------------


class TestRerank:
    def test_rerank_orders_by_boosted_score(self):
        """Lower-relevance chunk with a 2.0 boost should beat a higher-relevance neutral chunk."""
        high_rel_neutral = _chunk(
            chunk_id="c1",
            source_document="unknown.pdf",
            score=0.90,
        )
        low_rel_priority = _chunk(
            chunk_id="c2",
            book_name="Teal",
            chapter_number=8,
            pie_tags_by_band={"3-5": ["P"]},
            is_scripted_lesson=True,
            score=0.60,
        )
        result = rerank(
            [high_rel_neutral, low_rel_priority],
            query_type="SCRIPTED_ML",
            user_grade="4",
            writing_mode="Persuade",
            top_k=2,
        )
        # low_rel (0.6 × 2.0 = 1.2) beats high_rel (0.9 × 1.0 = 0.9)
        assert result[0].chunk_id == "c2"
        assert result[1].chunk_id == "c1"

    def test_rerank_mutates_score_in_place(self):
        chunk = _chunk(
            book_name="Teal",
            chapter_number=8,
            pie_tags_by_band={"3-5": ["P"]},
            is_scripted_lesson=True,
            score=0.50,
        )
        rerank(
            [chunk],
            query_type="SCRIPTED_ML",
            user_grade="4",
            writing_mode="Persuade",
            top_k=1,
        )
        # 0.50 × 2.0 = 1.0
        assert chunk.score == pytest.approx(1.0)

    def test_rerank_trims_to_top_k(self):
        chunks = [
            _chunk(chunk_id=f"c{i}", score=0.5 - 0.01 * i)
            for i in range(10)
        ]
        result = rerank(
            chunks,
            query_type="DEFAULT",
            user_grade=None,
            writing_mode=None,
            top_k=3,
        )
        assert len(result) == 3

    def test_rerank_empty_input(self):
        result = rerank(
            [],
            query_type="SCRIPTED_ML",
            user_grade="4",
            writing_mode="Persuade",
            top_k=5,
        )
        assert result == []

    def test_management_pushes_mini_lesson_chapter_down(self):
        """A semantically-strong match from chapter 8 should lose to chapter 3 when user asks about management."""
        ml_chunk = _chunk(
            chunk_id="ml",
            book_name="Teal",
            chapter_number=10,
            score=0.95,
        )
        mgmt_chunk = _chunk(
            chunk_id="mgmt",
            book_name="Teal",
            chapter_number=3,
            score=0.50,
        )
        result = rerank(
            [ml_chunk, mgmt_chunk],
            query_type="MANAGEMENT",
            user_grade=None,
            writing_mode=None,
            top_k=2,
        )
        # mgmt (0.50 × 2.0 = 1.0) beats ml (0.95 × 0.4 = 0.38)
        assert result[0].chunk_id == "mgmt"

    def test_early_writer_kills_3_12_content(self):
        """For EARLY_WRITER, a high-relevance 3-12 chunk should lose to a K-2 chunk."""
        teal = _chunk(
            chunk_id="teal",
            book_name="Teal",
            source_document="launching the writers workshop 3-12.pdf",
            score=0.95,
        )
        k2 = _chunk(
            chunk_id="k2",
            book_name="K-2",
            chapter_number=9,
            source_document="launching the writers workshop k-2.pdf",
            score=0.40,
        )
        result = rerank(
            [teal, k2],
            query_type="EARLY_WRITER",
            user_grade="K",
            writing_mode=None,
            top_k=2,
        )
        # k2 (0.40 × 2.0 = 0.80) beats teal (0.95 × 0.3 = 0.285)
        assert result[0].chunk_id == "k2"


# ---------------------------------------------------------------------------
# source_tier reconciliation (F18)
# ---------------------------------------------------------------------------


class TestSourceTierReconciliation:
    """Fix E-c: _source_tier must never let a boost<1.0 chunk outrank a boosted
    one. Verified via rerank() output order (tier-first)."""

    def test_management_episode_beats_wrong_audience_chapter(self):
        # Launch ch10 is a mini-lesson chapter — wrong audience for MANAGEMENT
        # (boost 0.4). The Ep 11 transcript is the relevant content (boost 1.3).
        ch10 = _chunk(chunk_id="ch10", book_name="Teal", chapter_number=10, score=0.9)
        ep11 = _chunk(chunk_id="ep11", source_document="Ep 11 script.pdf", score=0.3)
        ranked = rerank([ch10, ep11], query_type="MANAGEMENT",
                        user_grade="4", writing_mode=None, top_k=10)
        assert ranked[0].chunk_id == "ep11"

    def test_skill_seeking_pie_beats_wrong_chapter(self):
        # Launch workshop ch3 is wrong for a mini-lesson query (boost 0.7);
        # the Essential-Skills PIE is reference (boost 1.3). PIE must win.
        ch3 = _chunk(chunk_id="ch3", book_name="Teal", chapter_number=3, score=0.9)
        pie = _chunk(chunk_id="pie", source_document="Essential Skills PIE.pdf", score=0.5)
        ranked = rerank([ch3, pie], query_type="SCRIPTED_ML",
                        user_grade="4", writing_mode="Inform", top_k=10)
        assert ranked[0].chunk_id == "pie"

    def test_coaching_overview_not_tier_buried(self):
        # COACHING_GENERAL: overviews are NOT deprioritized (boost 2.0 for Launch).
        overview = _chunk(chunk_id="ov", book_name="Teal", score=0.5,
                          content_type="textbook_overview")
        other = _chunk(chunk_id="other", source_document="misc.pdf", score=0.9)
        ranked = rerank([other, overview], query_type="COACHING_GENERAL",
                        user_grade="4", writing_mode=None, top_k=10)
        assert ranked[0].chunk_id == "ov"
        # Win on TIER, not a score tiebreak: Launch overview is tier 1, other tier 4.
        assert (_source_tier(overview, "COACHING_GENERAL", "4", None)
                < _source_tier(other, "COACHING_GENERAL", "4", None))

    def test_plan_unit_overview_below_real_lesson(self):
        overview = _chunk(chunk_id="ov", book_name="Teal", score=0.9,
                          content_type="textbook_overview")
        pie = _chunk(chunk_id="pie", source_document="Essential Skills PIE.pdf", score=0.5)
        ranked = rerank([overview, pie], query_type="PLAN_UNIT",
                        user_grade="4", writing_mode="Inform", top_k=10)
        assert ranked[0].chunk_id == "pie"
        # Win on TIER, not a score tiebreak: PIE is tier 0, overview tier 4.
        assert (_source_tier(pie, "PLAN_UNIT", "4", "Inform")
                < _source_tier(overview, "PLAN_UNIT", "4", "Inform"))

    def test_coaching_launch_ch1_7_not_sunk(self):
        # F18 regression guard: COACHING_GENERAL gives ANY Launch chunk the top
        # boost (2.0, "always, always, always") with NO chapter deprioritize. The
        # skill-seeking ch1-7 tier sink must NOT fire for coaching — a Launch ch3
        # chunk must stay Launch-first (tier 1), above non-Launch core methodology
        # (tier 2). Before the query_type guard, ch3 wrongly sank to tier 4.
        ch3 = _chunk(chunk_id="ch3", book_name="Teal", chapter_number=3, score=0.5)
        core = _chunk(chunk_id="core",
                      source_document="Essential 2 explicit instruction.pdf", score=0.9)
        ranked = rerank([core, ch3], query_type="COACHING_GENERAL",
                        user_grade="4", writing_mode=None, top_k=10)
        assert ranked[0].chunk_id == "ch3"
        assert (_source_tier(ch3, "COACHING_GENERAL", "4", None)
                < _source_tier(core, "COACHING_GENERAL", "4", None))

    def test_think_aloud_wrong_chapter_still_sunk(self):
        # THINK_ALOUD routes to the same skill-seeking boost as SCRIPTED_ML, so it
        # DOES deprioritize Launch ch1-7 (0.7). The tier sink must fire for it too
        # (it is broader than _SKILL_SEEKING_QUERY_TYPES, which omits THINK_ALOUD):
        # a deprioritized ch3 must not outrank a boosted Essential-Skills PIE.
        ch3 = _chunk(chunk_id="ch3", book_name="Teal", chapter_number=3, score=0.9)
        pie = _chunk(chunk_id="pie", source_document="Essential Skills PIE.pdf", score=0.5)
        ranked = rerank([ch3, pie], query_type="THINK_ALOUD",
                        user_grade="4", writing_mode="Inform", top_k=10)
        assert ranked[0].chunk_id == "pie"
        assert (_source_tier(pie, "THINK_ALOUD", "4", "Inform")
                < _source_tier(ch3, "THINK_ALOUD", "4", "Inform"))


# ---------------------------------------------------------------------------
# Tier-vs-boost consistency invariant (F18 — the guard the design spec called for)
# ---------------------------------------------------------------------------


# The six query_types actually emitted by handlers/ and passed to rerank().
# (EARLY_WRITER / TRIGGER_SPECIFIC / DEFAULT are never emitted — excluded.)
_LIVE_QUERY_TYPES = [
    "SCRIPTED_ML",
    "HOW_TO_TEACH",
    "PLAN_UNIT",
    "THINK_ALOUD",
    "COACHING_GENERAL",
    "MANAGEMENT",
]


class TestTierBoostConsistency:
    """F18 invariant: `_source_tier` must never fight `priority_boost`.

    A pure global monotonicity (`boost(A) > boost(B) => tier(A) <= tier(B)`) is
    NOT a property of this system: tiers deliberately OVERRIDE boosts ACROSS
    source categories (that is the whole R2-H1 Launch-first fix — a low-boost
    Launch chunk categorically beats a higher-boost PIE/episode). So that literal
    form has by-design counter-examples (e.g. COACHING episode boost 1.3 tier 3
    vs library boost 1.0 tier 1) and cannot be asserted.

    The property that IS true — and that the ch1-7 / ch8-13 / overview penalties
    must preserve — is *within-source* agreement for LAUNCH content: a Launch
    chunk is boost-demoted (boost < NEUTRAL) iff it is tier-demoted (tier 4, the
    only penalty tier a Launch chunk can reach). This catches both the F18
    reconciliation bugs Task 5 fixed AND the COACHING/THINK_ALOUD ch1-7 guard
    regressions — a Launch chunk that is top-boosted but bottom-tiered (or
    deprioritized but not sunk) violates it.
    """

    _launch_chunks = {
        "launch_ch3": dict(book_name="Teal", chapter_number=3),      # ch1-7
        "launch_ch10": dict(book_name="Teal", chapter_number=10),    # ch8-13
        "launch_nochap": dict(book_name="Teal"),                     # no chapter
        "launch_overview": dict(book_name="Teal", content_type="textbook_overview"),
    }

    @pytest.mark.parametrize("query_type", _LIVE_QUERY_TYPES)
    @pytest.mark.parametrize("name", list(_launch_chunks))
    def test_launch_tier_demotion_matches_boost(self, query_type, name):
        """For every LIVE query_type, a Launch chunk lands in the penalty tier
        (4) exactly when its boost deprioritizes it (< NEUTRAL) — the tier side
        can never contradict the boost side."""
        chunk = _chunk(chunk_id=name, **self._launch_chunks[name])
        boost = priority_boost(chunk, query_type, user_grade="4", writing_mode=None)
        tier = _source_tier(chunk, query_type, user_grade="4", writing_mode=None)
        boost_demoted = boost < NEUTRAL
        tier_demoted = tier == 4
        assert boost_demoted == tier_demoted, (
            f"{query_type}/{name}: boost={boost} (demoted={boost_demoted}) but "
            f"tier={tier} (demoted={tier_demoted}) — tier fights boost"
        )


# ---------------------------------------------------------------------------
# Brady April non-negotiable #7 — NAMING a lesson beats the ch1-7 heuristic
# ---------------------------------------------------------------------------


class TestNamedLessonSurvivesTheCh17Sink:
    """"If user names/asks about a specific lesson from the book, don't ad lib
    or make it up. Pull on the exact lesson already described in the book."

    The ch1-7 sink (tier 4) says "this section is probably irrelevant to a
    skill query". That is a HEURISTIC about relevance. A teacher naming the
    lesson is a FACT, and the fact must win.

    Measured live: all 4 remaining ad-libs were ch1-7 lessons. "read up write
    down" scored 0.40 — BEATING the winning chunk's 0.25 — and still landed at
    rank 34, because tier 4 sinks it below every tier-1 chunk. Its own section
    made it unreachable no matter how explicitly it was named.
    """

    def _named_ch17(self, **kw):
        return _chunk(
            chunk_id="lww312-s4-ml5-read-up-write-down",
            source_document="Launching the Writers Workshop 3-12.pdf",
            book_name="Launching the Writers Workshop 3-12",
            chapter_number=4,
            lesson_trigger=["read-up-write-down"],
            score=0.4,
            **kw,
        )

    def test_named_ch17_lesson_is_not_sunk(self):
        out = rerank([self._named_ch17()], query_type="SCRIPTED_ML",
                     user_grade="4", writing_mode=None, top_k=5,
                     triggered_triggers=["read-up-write-down"])
        assert out[0].source_tier != 4, "a NAMED lesson must not sit in the penalty tier"

    def test_unnamed_ch17_lesson_still_sinks(self):
        """The F18 ch1-7 sink is correct for a generic skill query and must
        keep working — this fix is scoped to an explicit name, nothing else."""
        out = rerank([self._named_ch17()], query_type="SCRIPTED_ML",
                     user_grade="4", writing_mode=None, top_k=5,
                     triggered_triggers=None)
        assert out[0].source_tier == 4

    def test_named_ch17_lesson_outranks_a_higher_tier_rival(self):
        """The end-to-end regression: 'paraphrase' won at 0.25 while the named
        lesson sat at 0.40, rank 34."""
        rival = _chunk(chunk_id="lww312-s8-ml13-paraphrase",
                       source_document="Launching the Writers Workshop 3-12.pdf",
                       book_name="Launching the Writers Workshop 3-12",
                       chapter_number=8, score=0.25)
        out = rerank([rival, self._named_ch17()], query_type="SCRIPTED_ML",
                     user_grade="4", writing_mode=None, top_k=5,
                     triggered_triggers=["read-up-write-down"])
        assert out[0].chunk_id == "lww312-s4-ml5-read-up-write-down"

    def test_naming_never_beats_the_grade_band(self):
        """A K-2 lesson named by a 9th-grade teacher stays sunk: a wrong-
        audience chunk is boost-demoted far enough (0.4 x 1.5 = 0.6) that it
        remains below NEUTRAL, so the F18 tier/boost agreement holds and grade
        correctness still wins. Brady's grade lock outranks his naming rule."""
        k2 = _chunk(chunk_id="k2-s11-ml1-something",
                    source_document="Launching the Writers Workshop K-2.pdf",
                    book_name="Launching the Writers Workshop K-2",
                    chapter_number=11, grade_level="K-2",
                    lesson_trigger=["read-up-write-down"], score=0.9)
        out = rerank([k2], query_type="EARLY_WRITER", user_grade="9",
                     writing_mode=None, top_k=5,
                     triggered_triggers=["read-up-write-down"])
        assert out[0].score < 0.9, "a wrong-audience chunk must stay demoted even when named"


class TestManagementOwnsSections1To5NotOneToSeven:
    """Brady (feedback-docx.txt:140): "When 'routines, management, start up,
    writer's workshop, writer habits, expectations, procedures' are the focus,
    then Co-Pilot must pull from Sections 1-5 in the Launch books."
    requirements.md #14 says the same: "Management/routines as 4-step MLs
    (Part 1 of Launch books)".

    The code said ch 1-7 ("mgmt wants 1-7") and BOOSTED sections 6-7 at 2.0 for
    a management query. The corpus says what those sections are:
      1-5  purposes, daily instruction, writer's notebook, done-list/revision
           space, independent spellers        -> routines, procedures, habits
      6-7  define-trait, mentor texts, rubric building, assessment
      8-13 narrow topics, voice, word choice, fluency, punctuation -> SKILLS
    Sections 6-7 are traits and assessment — not routines. Measured live: a
    "how do I set up writing workshop routines" follow-up was topped by
    lww312-s6-ml1-define-trait-visually-verbally.

    Tier and boost move together — TestTierBoostConsistency locks their
    agreement, and a chunk demoted on one side but not the other is the exact
    F18 regression that guard exists to catch.
    """

    def _launch(self, ch: int):
        return _chunk(chunk_id=f"lww312-s{ch}-ml1",
                      source_document="Launching the Writers Workshop 3-12.pdf",
                      book_name="Launching the Writers Workshop 3-12",
                      chapter_number=ch, score=1.0)

    def test_sections_1_to_5_own_management(self):
        for ch in (1, 2, 3, 4, 5):
            assert priority_boost(self._launch(ch), "MANAGEMENT", "3", None) > NEUTRAL
            assert _source_tier(self._launch(ch), "MANAGEMENT", "3", None) == 0

    def test_traits_and_assessment_are_not_management(self):
        """6 = define-trait/mentor-text, 7 = rubrics. Brady's line stops at 5."""
        for ch in (6, 7):
            assert priority_boost(self._launch(ch), "MANAGEMENT", "3", None) < NEUTRAL
            assert _source_tier(self._launch(ch), "MANAGEMENT", "3", None) == 4

    def test_skill_chapters_stay_wrong_audience(self):
        for ch in (8, 10, 13):
            assert priority_boost(self._launch(ch), "MANAGEMENT", "3", None) < NEUTRAL
            assert _source_tier(self._launch(ch), "MANAGEMENT", "3", None) == 4

    def test_a_skill_query_is_unaffected(self):
        """The mirror rule (ch 1-7 deprioritized under SCRIPTED_ML) is Brady's
        too and must not move — this changes the MANAGEMENT side only."""
        assert priority_boost(self._launch(4), "SCRIPTED_ML", "3", None) < NEUTRAL
        assert priority_boost(self._launch(10), "SCRIPTED_ML", "3", None) >= NEUTRAL
