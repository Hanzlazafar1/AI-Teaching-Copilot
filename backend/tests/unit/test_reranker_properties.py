"""Property-based tests for the Phase 6 reranker.

These tests assert ordering PROPERTIES, not specific boost values. If the
coefficients are retuned in the future, these tests should still pass as
long as the underlying principle holds:

  P1. Launch content beats episode scripts for skill-seeking queries.
  P2. Mode-dedicated titles outrank mode-tagged generic chunks.
  P3. Overviews are deprioritized for skill-seeking queries.
  P4. Chapter-role targeting is mirror-symmetric (mgmt vs. mini-lesson).
  P5. Grade-band targeting is bidirectional (wrong-audience deprio applies
      to both sentence-era chapters for pre-sentence writers AND the
      3-12 book for EARLY_WRITER).
  P6. Trigger-tag match boosts over BM25-adjacent chunks.

Each test builds two chunks that differ only in one attribute and asserts
the correct one ranks first after priority_boost is applied. That way the
principle is verified regardless of the exact coefficient numbers.
"""

from __future__ import annotations

import pytest

from retrieval.reranker import (
    BOOST_TRIGGER_TAG_MATCH,
    priority_boost,
    rerank,
)
from retrieval.search import RetrievedChunk


def _chunk(
    chunk_id: str = "c",
    source_document: str = "",
    book_name: str | None = None,
    chapter_number: int | None = None,
    ml_number: int | None = None,
    skill_title: str = "",
    pie_tags_by_band: dict | None = None,
    page_number: int | None = None,
    writing_mode: str = "",
    is_scripted_lesson: bool = False,
    content_type: str = "",
    lesson_trigger: list | None = None,
    score: float = 1.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_document=source_document,
        content_type=content_type,
        content="",
        grade_level="",
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
        lesson_trigger=lesson_trigger or [],
    )


def _launch_ml(**overrides) -> RetrievedChunk:
    base = dict(
        book_name="Teal",
        chapter_number=9,
        ml_number=1,
        is_scripted_lesson=True,
        content_type="textbook_lesson",
    )
    base.update(overrides)
    return _chunk(**base)


def _launch_overview(**overrides) -> RetrievedChunk:
    base = dict(
        book_name="Teal",
        content_type="textbook_overview",
        skill_title="Overview",
    )
    base.update(overrides)
    return _chunk(**base)


def _episode(**overrides) -> RetrievedChunk:
    base = dict(
        source_document="Ep 3 SEC Script.pdf",
        content_type="episode_explanation",
    )
    base.update(overrides)
    return _chunk(**base)


# ---------------------------------------------------------------------------
# P1 — Launch beats episodes for skill-seeking queries
# ---------------------------------------------------------------------------


class TestP1_LaunchBeatsEpisodeForSkillQueries:
    @pytest.mark.parametrize("qt", ["SCRIPTED_ML", "HOW_TO_TEACH", "PLAN_UNIT"])
    def test_launch_ml_outranks_episode_at_equal_score(self, qt):
        launch = _launch_ml(
            chunk_id="launch",
            skill_title="How to do X",
            writing_mode="Persuade",
            pie_tags_by_band={"3-5": ["P"]},
            score=0.5,
        )
        ep = _episode(chunk_id="ep", score=0.5)
        result = rerank(
            [launch, ep],
            query_type=qt,
            user_grade="4",
            writing_mode="Persuade",
            top_k=2,
        )
        assert result[0].chunk_id == "launch", (
            f"P1 violated: under {qt}, Launch ML should outrank episode "
            f"at equal pre-boost score."
        )


# ---------------------------------------------------------------------------
# P2 — Mode-dedicated titles outrank mode-tagged generic chunks
# ---------------------------------------------------------------------------


class TestP2_ModeDedicatedOutranksModeTagged:
    @pytest.mark.parametrize("qt", ["SCRIPTED_ML", "HOW_TO_TEACH", "PLAN_UNIT"])
    @pytest.mark.parametrize(
        "mode,adjective",
        [("Persuade", "persuasive"), ("Inform", "informative"), ("Entertain", "narrative")],
    )
    def test_dedicated_beats_tagged(self, qt, mode, adjective):
        # Dedicated: skill_title contains the mode adjective.
        dedicated = _launch_ml(
            chunk_id="dedicated",
            skill_title=f"Craft {adjective} introductions",
            writing_mode=mode,
            pie_tags_by_band={"3-5": ["P"] if mode == "Persuade" else ["I"] if mode == "Inform" else ["E"]},
            score=0.5,
        )
        # Tagged-only: pacing tag for mode, generic title.
        tagged = _launch_ml(
            chunk_id="tagged",
            skill_title="A general writing skill",
            writing_mode="all",
            pie_tags_by_band={"3-5": ["P"] if mode == "Persuade" else ["I"] if mode == "Inform" else ["E"]},
            score=0.5,
        )
        result = rerank(
            [tagged, dedicated],
            query_type=qt,
            user_grade="4",
            writing_mode=mode,
            top_k=2,
        )
        assert result[0].chunk_id == "dedicated", (
            f"P2 violated: under {qt} with {mode}, a title-dedicated lesson "
            f"must outrank a merely pacing-tagged lesson at equal pre-boost score."
        )


# ---------------------------------------------------------------------------
# P3 — Overviews deprioritized for skill-seeking queries
# ---------------------------------------------------------------------------


class TestP3_OverviewsDeprioritizedForSkillQueries:
    @pytest.mark.parametrize("qt", ["SCRIPTED_ML", "HOW_TO_TEACH", "PLAN_UNIT"])
    def test_actual_lesson_beats_overview_at_equal_score(self, qt):
        lesson = _launch_ml(
            chunk_id="lesson",
            writing_mode="Persuade",
            pie_tags_by_band={"3-5": ["P"]},
            score=0.5,
        )
        overview = _launch_overview(chunk_id="overview", score=0.5)
        result = rerank(
            [overview, lesson],
            query_type=qt,
            user_grade="4",
            writing_mode="Persuade",
            top_k=2,
        )
        assert result[0].chunk_id == "lesson", (
            f"P3 violated: under {qt}, a real lesson chunk must outrank an "
            f"overview chunk at equal pre-boost score."
        )

    def test_overview_not_deprioritized_for_coaching_general(self):
        """COACHING_GENERAL doesn't apply P3 — overview can be informative here."""
        lesson = _launch_ml(
            chunk_id="lesson",
            writing_mode="Persuade",
            score=0.5,
        )
        overview = _launch_overview(chunk_id="overview", score=0.5)
        # Both get the same launch-book boost under COACHING_GENERAL, so equal
        # pre-boost → ties on position. The assertion here is that overview is
        # NOT actively penalized (boosts equal).
        b_lesson = priority_boost(lesson, "COACHING_GENERAL", "4", "Persuade")
        b_overview = priority_boost(overview, "COACHING_GENERAL", "4", "Persuade")
        assert b_overview == b_lesson, (
            "Under COACHING_GENERAL, overview and lesson chunks must receive "
            "equal boost — overviews are informative context here, not noise."
        )


# ---------------------------------------------------------------------------
# P4 — Chapter-role targeting is mirror-symmetric
# ---------------------------------------------------------------------------


class TestP4_ChapterRoleTargeting:
    def test_scripted_ml_deprioritizes_management_chapters(self):
        """For mini-lesson queries, workshop-setup chapters (1-7) are wrong."""
        mini_lesson_ch = _launch_ml(chunk_id="ml", chapter_number=9)
        mgmt_ch = _launch_ml(chunk_id="mgmt", chapter_number=3)
        # Without mode context the ML chunk is neutral (1.0), mgmt chunk is deprio (0.7).
        result = rerank(
            [mgmt_ch, mini_lesson_ch],
            query_type="SCRIPTED_ML",
            user_grade=None,
            writing_mode=None,
            top_k=2,
        )
        assert result[0].chunk_id == "ml"

    def test_management_deprioritizes_mini_lesson_chapters(self):
        """Mirror: for management queries, mini-lesson chapters (8-13) are wrong."""
        mgmt_ch = _launch_ml(chunk_id="mgmt", chapter_number=3)
        mini_lesson_ch = _launch_ml(chunk_id="ml", chapter_number=9)
        result = rerank(
            [mini_lesson_ch, mgmt_ch],
            query_type="MANAGEMENT",
            user_grade=None,
            writing_mode=None,
            top_k=2,
        )
        assert result[0].chunk_id == "mgmt"


# ---------------------------------------------------------------------------
# P5 — Bidirectional grade-band targeting
# ---------------------------------------------------------------------------


class TestP5_GradeBandTargeting:
    def test_early_writer_k2_chapter_11_deprioritized(self):
        """Pre-sentence writers need drawing/labeling, not sentence-writing content."""
        drawing_chunk = _chunk(
            chunk_id="draw",
            book_name="K-2",
            chapter_number=8,
            content_type="textbook_lesson",
            score=0.5,
        )
        sentence_chunk = _chunk(
            chunk_id="sent",
            book_name="K-2",
            chapter_number=11,
            content_type="textbook_lesson",
            score=0.5,
        )
        result = rerank(
            [sentence_chunk, drawing_chunk],
            query_type="EARLY_WRITER",
            user_grade="K",
            writing_mode=None,
            top_k=2,
        )
        assert result[0].chunk_id == "draw"

    def test_early_writer_3_12_book_deprioritized(self):
        """For K-2 EARLY_WRITER, the 3-12 book is wrong audience."""
        k2_chunk = _chunk(
            chunk_id="k2",
            book_name="K-2",
            chapter_number=8,
            content_type="textbook_lesson",
            score=0.5,
        )
        teal_chunk = _chunk(
            chunk_id="teal",
            book_name="Teal",
            source_document="Launching the Writers Workshop 3-12.pdf",
            chapter_number=8,
            content_type="textbook_lesson",
            score=0.5,
        )
        result = rerank(
            [teal_chunk, k2_chunk],
            query_type="EARLY_WRITER",
            user_grade="K",
            writing_mode=None,
            top_k=2,
        )
        assert result[0].chunk_id == "k2"


# ---------------------------------------------------------------------------
# P6 — Trigger-tag match wins over BM25-adjacent chunks
# ---------------------------------------------------------------------------


class TestP6_TriggerTagMatch:
    def test_trigger_tagged_chunk_gets_boost(self):
        """Equal pre-boost score + one has the matched trigger tag → tagged wins."""
        tagged = _launch_ml(
            chunk_id="tagged",
            lesson_trigger=["pizza-table"],
            score=0.5,
        )
        untagged = _launch_ml(
            chunk_id="untagged",
            lesson_trigger=[],
            score=0.5,
        )
        result = rerank(
            [untagged, tagged],
            query_type="HOW_TO_TEACH",
            user_grade="4",
            writing_mode=None,
            top_k=2,
            triggered_triggers=["pizza-table"],
        )
        assert result[0].chunk_id == "tagged"

    def test_trigger_boost_preserves_meaningful_margin(self):
        """A trigger-tagged chunk beats a BM25-adjacent chunk with up to ~50%
        higher pre-boost score (the BOOST_TRIGGER_TAG_MATCH margin)."""
        assert BOOST_TRIGGER_TAG_MATCH >= 1.3, (
            "Trigger-tag boost must be ≥ 1.3× to ensure tagged chunks beat "
            "adjacent chunks with modestly higher BM25 scores."
        )

    def test_trigger_boost_only_applies_when_tag_matches(self):
        """A chunk tagged with a DIFFERENT trigger than the query's matched
        trigger does NOT get the boost."""
        tagged_other = _launch_ml(
            chunk_id="tagged_other",
            lesson_trigger=["slinky-test"],  # not pizza-table
            score=0.5,
        )
        untagged = _launch_ml(
            chunk_id="untagged",
            lesson_trigger=[],
            score=0.5,
        )
        # Equal pre-boost, no matching tag → boost-neutral, order stable.
        result = rerank(
            [tagged_other, untagged],
            query_type="HOW_TO_TEACH",
            user_grade="4",
            writing_mode=None,
            top_k=2,
            triggered_triggers=["pizza-table"],
        )
        # Either order is acceptable (it's a tie), but neither should have
        # been boosted above the other by the trigger-match logic.
        assert tagged_other.score == untagged.score, (
            "Trigger-match boost leaked to a chunk tagged with a non-matching trigger."
        )


# ---------------------------------------------------------------------------
# Coefficient-ordering invariants — the documented principles require
# specific coefficient inequalities to hold. Fail fast if a future retune
# breaks them.
# ---------------------------------------------------------------------------


class TestCoefficientInvariants:
    def test_mode_in_title_exceeds_pie_tag_boost(self):
        """P2: mode-dedicated title must outrank pie-tag-only Launch chunks."""
        from retrieval.reranker import BOOST_MODE_IN_TITLE, BOOST_PIE_TAG_BAND_MODE
        assert BOOST_MODE_IN_TITLE > BOOST_PIE_TAG_BAND_MODE, (
            "BOOST_MODE_IN_TITLE must exceed BOOST_PIE_TAG_BAND_MODE — "
            "otherwise title-dedicated lessons tie with merely-tagged ones."
        )

    def test_overview_deprioritize_actually_penalizes(self):
        """P3: deprioritize must be < 1.0, not just 'not boosted'."""
        from retrieval.reranker import DEPRIO_OVERVIEW_SKILL_QUERIES, NEUTRAL
        assert DEPRIO_OVERVIEW_SKILL_QUERIES < NEUTRAL, (
            "Overview deprioritize must be below neutral, not neutral."
        )

    def test_essential_skills_pie_tops_plan_unit(self):
        """PLAN_UNIT: the PIE doc is canonical; no other source should outrank it."""
        from retrieval.reranker import (
            BOOST_PLAN_UNIT_ESSENTIAL_SKILLS,
            BOOST_PLAN_UNIT_PACING_PAGE,
            BOOST_MODE_IN_TITLE,
        )
        assert BOOST_PLAN_UNIT_ESSENTIAL_SKILLS > BOOST_PLAN_UNIT_PACING_PAGE
        assert BOOST_PLAN_UNIT_ESSENTIAL_SKILLS > BOOST_MODE_IN_TITLE, (
            "For PLAN_UNIT, the Essential Skills PIE doc is canonical and must "
            "outrank even mode-dedicated Launch chunks."
        )

    def test_ask_user_threshold_within_verbatim_band(self):
        """Threshold 'ask user' must sit just below 'return verbatim' — a
        narrow band keeps offers high-signal."""
        from retrieval.library_precheck import (
            ASK_USER_CONFIDENCE_THRESHOLD,
            VERBATIM_CONFIDENCE_THRESHOLD,
        )
        gap = VERBATIM_CONFIDENCE_THRESHOLD - ASK_USER_CONFIDENCE_THRESHOLD
        assert 0.01 <= gap <= 0.10, (
            f"ASK_USER should sit in a [0.01, 0.10] band below VERBATIM_AUTO "
            f"(got gap={gap:.2f}). Wider bands produce too many false offers; "
            f"narrower bands collapse the ASK_USER tier."
        )
