"""Phase 6 — Priority-weighted re-ranking of hybrid search results.

Section 13 of BRADY-ALIGNMENT-PLAN.md. Between hybrid-search (top-20
candidates) and the caller (top-K), each candidate's `relevance_score`
is multiplied by a `priority_boost` that depends on the query_type,
the user's grade band, the writing mode, and the chunk's source.

Principles this module enforces (each principle drives a coefficient):
  P1. Launch book beats episode scripts for skill-seeking queries.
      Brady: "always, always, always" start with Launch content.
  P2. Mode-dedicated chunks (skill_title literally names the writing mode)
      outrank chunks merely pacing-tagged for that mode. A lesson titled
      "Craft persuasive introductions" is dedicated; a lesson tagged as
      relevant to persuasive writing but about a different skill is not.
  P3. Overviews describe sections — they are not teachable skills. They
      are deprioritized for ALL skill-seeking query_types (SCRIPTED_ML,
      HOW_TO_TEACH, TRIGGER_SPECIFIC, PLAN_UNIT), neutral elsewhere.
  P4. Workshop-management chapters (Launch ch 1-7) are wrong for mini-
      lesson queries; mini-lesson chapters (8-13) are wrong for classroom-
      management queries. Mirror-symmetric deprioritize rules.
  P5. Grade-band targeting is bidirectional. K-2 pre-sentence writers
      need drawing/labeling (K-2 ch 8-10); they do NOT need K-2 ch 11+
      (sentence-era) or anything from the 3-12 book.
  P6. When query expansion matched a Smekens trigger, chunks explicitly
      tagged with that trigger outrank chunks that merely contain the
      trigger synonym via BM25.

Coefficient calibration notes (why each number is what it is):
  - Skill-seeking boosts sit in a [0.3, 2.0] band. The 2.0 ceiling reserves
    room for the mode-dedicated title boost to still dominate among Launch
    content when the user specified a mode (see P2). 0.3 is used only for
    wrong-audience content (3-12 book for K-2 writers).
  - Mode-dedicated title boost = 2.2 — sits just above the strongest
    alternative (pacing pie-tag + user band + mode = 2.0) so title-
    dedicated chunks edge ahead on equal pre-boost score, without forcing
    pacing-tagged chunks out of relevance (margin = +0.2 = 10%).
  - Overview deprioritize = 0.5 — halves overview score, enough to push
    overviews below dedicated lessons of comparable semantic match but not
    so aggressive that a high-semantic-match overview is invisible.
  - Trigger-match boost = 1.5 — chunks tagged with a matched trigger can
    beat a BM25-adjacent chunk with up to 50% higher pre-boost score.
    This preserves priority for the chunk that actually TEACHES the
    trigger even when generic-relevance chunks score higher semantically.

When adding a new boost: state the principle, the margin it preserves
against the next-weaker/next-stronger boost, and add a property test in
tests/unit/test_reranker.py that asserts the ordering holds.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from retrieval.search import RetrievedChunk

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_LIBRARY_PATH = _ROOT / "data" / "scripted_ml_library.json"


# ---------------------------------------------------------------------------
# Coefficient catalog — every magic number here has a named rationale.
# Change them only after updating both the principle comment AND the property
# test that enforces the principle.
# ---------------------------------------------------------------------------

# P1 — skill-seeking source priority
BOOST_PIE_TAG_BAND_MODE = 2.0        # Launch + pie_tags_by_band[user_band] has mode
BOOST_LIBRARY_SOURCE_MODE = 1.8      # Library-backed chunk + mode pie tag
BOOST_LAUNCH_ML_MODE_MATCH = 1.5     # Launch ML with writing_mode field == mode
BOOST_ESSENTIAL_SKILLS_MODE = 1.3    # Essential Skills PIE doc + mode given

# P2 — mode-dedicated skill-title boost (applies across SCRIPTED_ML /
# HOW_TO_TEACH / PLAN_UNIT / TRIGGER_SPECIFIC when writing_mode is set).
# Sits above BOOST_PIE_TAG_BAND_MODE (2.0) by a deliberate margin so a
# title-dedicated chunk edges ahead on equal pre-boost score.
BOOST_MODE_IN_TITLE = 2.2

# P3 — overview deprioritize. Applied to skill-seeking queries where the
# user wants a specific lesson, not a summary.
DEPRIO_OVERVIEW_SKILL_QUERIES = 0.5

# P4 — chapter-role deprioritize (mini-lessons want ch 8-13; mgmt wants 1-5).
DEPRIO_WRONG_CHAPTER = 0.7           # ch 1-7 under SCRIPTED_ML/HOW_TO_TEACH
DEPRIO_WRONG_MGMT = 0.4              # ch 6-13 under MANAGEMENT

# Brady's "Sections 1-5" — the management half of the Launch books ("Part 1").
# ONE constant so the boost and the tier can never disagree about where
# management ends; TestTierBoostConsistency locks that they don't. Deliberately
# NOT symmetric with DEPRIO_WRONG_CHAPTER's ch 1-7: sections 6-7 (define-trait,
# mentor texts, rubrics) are neither routines NOR skill mini-lessons, so they
# are wrong-audience for a management query while still being deprioritized for
# a skill query.
_MGMT_LAST_CHAPTER = 5

# P5 — bidirectional grade targeting
BOOST_K2_PRESENTENCE = 2.0           # K-2 ch 8-10 (Drawing/Labeling/early)
BOOST_K2_DRAW_LABEL_TITLE = 1.8      # K-2 lesson titled with draw/label
BOOST_K2_OTHER = 1.2                 # K-2 elsewhere, still better than non-K-2
DEPRIO_K2_POST_SENTENCE = 0.4        # K-2 ch 11+ for pre-sentence writers
DEPRIO_WRONG_BOOK_FOR_EARLY = 0.3    # 3-12 book for EARLY_WRITER queries

# PLAN_UNIT specifics
BOOST_PLAN_UNIT_ESSENTIAL_SKILLS = 2.5  # PIE doc is the canonical source
BOOST_PLAN_UNIT_PACING_PAGE = 1.8       # Launch pacing pages = runners-up
BOOST_PLAN_UNIT_LAUNCH_WITH_TAG = 1.3   # Launch chunk pacing-tagged for mode
BOOST_PLAN_UNIT_MODE_FIELD_MATCH = 1.2  # Launch chunk writing_mode matches
DEPRIO_PLAN_UNIT_EPISODE = 0.5          # Episodes are transcripts, not plans

# COACHING_GENERAL (Brady: Launch always-always-always)
BOOST_COACHING_LAUNCH = 2.0
BOOST_COACHING_CORE_METHODOLOGY = 1.5    # Essential 2, Master 4-step, Think-Aloud
BOOST_COACHING_EPISODE = 1.3
BOOST_COACHING_TRAINING_TRANSCRIPT = 1.1

# MANAGEMENT
BOOST_MGMT_TWPDMS_EP11 = 1.3
BOOST_MGMT_EP1_K12 = 1.2

# P6 — trigger-tag match
BOOST_TRIGGER_TAG_MATCH = 1.5

NEUTRAL = 1.0

# Named tiers, so the ch1-7 un-sink below reads as what it means rather than as
# two bare integers. Values unchanged — see _source_tier.
_TIER_CH17_SUNK = 4       # Launch ch1-7 under a skill-seeking query
_TIER_OTHER_LAUNCH = 1    # "any other Launch content"


# ---------------------------------------------------------------------------
# Library-source-chunk set (chunks that back a library entry)
# ---------------------------------------------------------------------------

_LIBRARY_SOURCE_CHUNK_IDS: frozenset[str] = frozenset()
try:
    _lib = json.loads(_LIBRARY_PATH.read_text())
    _LIBRARY_SOURCE_CHUNK_IDS = frozenset(
        e["source_chunk_id"] for e in _lib.get("entries", []) if e.get("source_chunk_id")
    )
except FileNotFoundError:
    logger.warning("scripted_ml_library.json missing — library-source boost disabled")


# ---------------------------------------------------------------------------
# Grade + mode helpers
# ---------------------------------------------------------------------------


def grade_to_band(grade: str | None) -> str | None:
    """Map a concrete grade to its pacing band. None → None."""
    if grade is None:
        return None
    g = str(grade).strip()
    if g in {"K", "1", "2"}:
        return "K-2"
    if g in {"3", "4", "5"}:
        return "3-5"
    if g in {"6", "7", "8"}:
        return "6-8"
    if g in {"9", "10", "11", "12"}:
        return "9-12"
    if g in {"K-2", "3-5", "6-8", "9-12"}:
        return g
    return None


_MODE_TO_TAG = {"Persuade": "P", "Inform": "I", "Entertain": "E"}

# Adjective forms teachers actually use in skill titles vs. the Smekens
# canonical verb forms. Lets a chunk titled "Craft persuasive introductions"
# match a writing_mode of "Persuade".
_MODE_ADJECTIVE = {
    "persuade": "persuasive",
    "inform": "informative",
    "entertain": "narrative",
}


def _mode_adjective(mode_lower: str) -> str:
    return _MODE_ADJECTIVE.get(mode_lower, "")


def _mode_appears_in_title(chunk: RetrievedChunk, writing_mode: str | None) -> bool:
    """True when the chunk's skill_title literally contains the writing mode
    (as verb OR adjective). Key P2 signal — identifies mode-dedicated lessons.
    """
    if not writing_mode:
        return False
    mode = writing_mode.lower()
    adj = _mode_adjective(mode)
    title = (chunk.skill_title or "").lower()
    return (mode in title) or (bool(adj) and adj in title)


# ---------------------------------------------------------------------------
# Source/content-type helpers
# ---------------------------------------------------------------------------


def _is_launch_book(chunk: RetrievedChunk) -> bool:
    """Launch book = Teal (3-12) or K-2 Launch. Check book_name first, then source."""
    if chunk.book_name in ("Teal", "K-2"):
        return True
    src = (chunk.source_document or "").lower()
    return "launching the writers workshop" in src


def _is_essential_skills_pie(chunk: RetrievedChunk) -> bool:
    """The Essential Skills PIE doc lists priority skills per grade+mode — the
    canonical source for PLAN_UNIT responses.
    """
    src = (chunk.source_document or "").lower()
    return "skill 1" in src or "skill 2" in src or "essential skills" in src


def _is_core_methodology(chunk: RetrievedChunk) -> bool:
    """Essential 2, Master 4-step, Think-Aloud Scripts — Smekens core methodology."""
    src = (chunk.source_document or "").lower()
    return (
        "essential 2" in src
        or "master the 4-step" in src
        or "think-aloud scripts" in src
    )


def _is_episode_script(chunk: RetrievedChunk) -> bool:
    src = (chunk.source_document or "").lower()
    return src.startswith("ep ") and "script" in src


def _is_twpdms_ep11(chunk: RetrievedChunk) -> bool:
    src = (chunk.source_document or "").lower()
    return "ep 11" in src


def _is_ep1_k12(chunk: RetrievedChunk) -> bool:
    src = (chunk.source_document or "").lower()
    return "ep 1 k-12" in src


def _is_library_source(chunk: RetrievedChunk) -> bool:
    return chunk.chunk_id in _LIBRARY_SOURCE_CHUNK_IDS


def _is_pacing_page_chunk(chunk: RetrievedChunk) -> bool:
    """Launch-book pacing pages have page_number populated (from data/launch_book_pacing.json)."""
    return _is_launch_book(chunk) and chunk.page_number is not None


def _is_overview_chunk(chunk: RetrievedChunk) -> bool:
    """Chunks that describe a section rather than teach a skill. They're
    unhelpful for skill-seeking queries — user wants the actual lesson.
    `textbook_overview` is the canonical content_type; `overview` in
    skill_title/section_name catches stragglers."""
    ct = (chunk.content_type or "").lower()
    if ct == "textbook_overview":
        return True
    # Fallback: explicit 'overview' in the section/title and no ML number.
    sec = (chunk.section_name or "").lower() if hasattr(chunk, "section_name") else ""
    title = (chunk.skill_title or "").lower()
    has_overview_label = "overview" in sec or title.startswith("overview")
    return has_overview_label and not chunk.ml_number


def _has_pie_tag(chunk: RetrievedChunk, band: str | None, mode_tag: str) -> bool:
    """True if the chunk has pie_tags_by_band[band] containing mode_tag."""
    if not band or not chunk.pie_tags_by_band:
        return False
    return mode_tag in (chunk.pie_tags_by_band.get(band) or [])


def _is_k2_book(chunk: RetrievedChunk) -> bool:
    src = (chunk.source_document or "").lower()
    return chunk.book_name == "K-2" or "k-2.pdf" in src


# ---------------------------------------------------------------------------
# Shared deprioritize check for overview content across skill-seeking queries.
# Applying this in one place ensures every skill-seeking query_type treats
# overviews the same way (P3).
# ---------------------------------------------------------------------------


def _overview_penalty_if_applicable(chunk: RetrievedChunk) -> float | None:
    """Returns DEPRIO_OVERVIEW_SKILL_QUERIES if the chunk is an overview, else None.

    The caller decides whether to apply it. All skill-seeking query_types
    (SCRIPTED_ML, HOW_TO_TEACH, TRIGGER_SPECIFIC, PLAN_UNIT) apply it;
    COACHING_GENERAL and MANAGEMENT do not (overviews can be informative there).
    """
    if _is_overview_chunk(chunk):
        return DEPRIO_OVERVIEW_SKILL_QUERIES
    return None


# Single source of truth for which query_types deprioritize overview chunks.
# Mirrors _overview_penalty_if_applicable's contract; consumed by _source_tier
# so the tier side can't drift from the boost side. The tier/boost agreement this
# preserves is locked by TestTierBoostConsistency in tests/unit/test_reranker.py.
_NO_OVERVIEW_PENALTY = frozenset({"MANAGEMENT", "COACHING_GENERAL", "EARLY_WRITER"})


def _applies_overview_penalty(query_type: str) -> bool:
    return query_type not in _NO_OVERVIEW_PENALTY


# Query types whose Launch ch1-7 chunks must NOT be sunk to tier 4 in the
# skill-seeking fall-through: COACHING_GENERAL (Launch wins "always, always,
# always", boost 2.0) and EARLY_WRITER (own K-2 audience logic) reach that
# branch but do NOT apply DEPRIO_WRONG_CHAPTER, so sinking their ch1-7 would
# make the tier contradict the boost (the F18 regression the guard prevents).
# Deliberately distinct from _NO_OVERVIEW_PENALTY — MANAGEMENT is absent here
# because it returns from _source_tier before the ch1-7 sink is reached.
# Tier/boost agreement is locked by TestTierBoostConsistency.
_NO_CH17_SINK = frozenset({"COACHING_GENERAL", "EARLY_WRITER"})


# ---------------------------------------------------------------------------
# Boost rules per query_type
# ---------------------------------------------------------------------------


def _boost_scripted_or_how_to(
    chunk: RetrievedChunk,
    user_band: str | None,
    writing_mode: str | None,
) -> float:
    """SCRIPTED_ML / HOW_TO_TEACH / TRIGGER_SPECIFIC / DEFAULT.

    Enforces P1 (Launch priority), P2 (mode-dedicated titles), P3 (overviews
    deprioritized), P4 (mgmt chapters wrong for skill queries).
    """
    # P3 — overviews don't teach skills.
    op = _overview_penalty_if_applicable(chunk)
    if op is not None:
        return op

    # P2 — mode-dedicated title wins.
    if _is_launch_book(chunk) and _mode_appears_in_title(chunk, writing_mode):
        return BOOST_MODE_IN_TITLE

    mode_tag = _MODE_TO_TAG.get(writing_mode or "")

    # P1 — Launch + pie tag for user's band + mode.
    if _is_launch_book(chunk) and mode_tag and _has_pie_tag(chunk, user_band, mode_tag):
        return BOOST_PIE_TAG_BAND_MODE

    # P1 — library-backed + pacing tag.
    if _is_library_source(chunk) and mode_tag and _has_pie_tag(chunk, user_band, mode_tag):
        return BOOST_LIBRARY_SOURCE_MODE

    # P1 — Launch ML with matching writing_mode (field-level).
    if (
        _is_launch_book(chunk)
        and chunk.is_scripted_lesson
        and mode_tag
        and (chunk.writing_mode or "").lower() == (writing_mode or "").lower()
    ):
        return BOOST_LAUNCH_ML_MODE_MATCH

    # P1 — Essential Skills PIE with mode context.
    if _is_essential_skills_pie(chunk) and mode_tag:
        return BOOST_ESSENTIAL_SKILLS_MODE

    # P4 — workshop-management chapters are wrong for mini-lesson queries.
    if _is_launch_book(chunk) and chunk.chapter_number and 1 <= chunk.chapter_number <= 7:
        return DEPRIO_WRONG_CHAPTER

    return NEUTRAL


def _boost_plan_unit(
    chunk: RetrievedChunk,
    writing_mode: str | None = None,
) -> float:
    """PLAN_UNIT — the user wants a priority-skill sequence, not a daily breakdown.

    Enforces P1 (Launch priority), P2 (mode-dedicated titles), P3 (overviews
    deprioritized — applied centrally).
    """
    # P3 — overviews don't help plan a unit (first to block them out).
    op = _overview_penalty_if_applicable(chunk)
    if op is not None:
        return op

    # PIE doc is canonical for unit plans.
    if _is_essential_skills_pie(chunk):
        return BOOST_PLAN_UNIT_ESSENTIAL_SKILLS
    if _is_pacing_page_chunk(chunk):
        return BOOST_PLAN_UNIT_PACING_PAGE

    # P2 — mode-dedicated Launch lessons (e.g., "Craft persuasive introductions")
    # are what unit plans should be built from when a mode is specified.
    if _is_launch_book(chunk) and _mode_appears_in_title(chunk, writing_mode):
        return BOOST_MODE_IN_TITLE

    if _is_launch_book(chunk):
        mode_tag = _MODE_TO_TAG.get(writing_mode or "")
        if mode_tag:
            if any(mode_tag in (bt or []) for bt in (chunk.pie_tags_by_band or {}).values()):
                return BOOST_PLAN_UNIT_LAUNCH_WITH_TAG
            if (chunk.writing_mode or "").lower() == (writing_mode or "").lower():
                return BOOST_PLAN_UNIT_MODE_FIELD_MATCH
        return NEUTRAL

    if _is_episode_script(chunk):
        return DEPRIO_PLAN_UNIT_EPISODE

    return NEUTRAL


def _boost_management(chunk: RetrievedChunk) -> float:
    """MANAGEMENT — workshop routines/procedures. Launch ch 1-5 owns this
    space; everything above it is wrong audience (P4 mirror-symmetric rule).

    Brady (feedback-docx.txt:140): "When 'routines, management, start up,
    writer's workshop, writer habits, expectations, procedures' are the focus,
    then Co-Pilot must pull from Sections 1-5 in the Launch books" —
    requirements.md #14 says the same ("Part 1 of Launch books"). This said
    1-7 and BOOSTED sections 6-7 at 2.0, which is why a routines question was
    topped live by lww312-s6-ml1-define-trait-visually-verbally.

    The corpus agrees with him: 1-5 are purposes / daily instruction / the
    writer's notebook / done-list / independent spellers — routines and
    habits. 6-7 are define-trait, mentor texts and rubric building: trait
    instruction and assessment, not management.
    """
    if _is_launch_book(chunk) and chunk.chapter_number:
        if 1 <= chunk.chapter_number <= _MGMT_LAST_CHAPTER:
            return BOOST_PIE_TAG_BAND_MODE  # 2.0
        if _MGMT_LAST_CHAPTER < chunk.chapter_number <= 13:
            return DEPRIO_WRONG_MGMT
    if _is_twpdms_ep11(chunk):
        return BOOST_MGMT_TWPDMS_EP11
    if _is_ep1_k12(chunk):
        return BOOST_MGMT_EP1_K12
    return NEUTRAL


def _boost_early_writer(chunk: RetrievedChunk) -> float:
    """EARLY_WRITER — K-2 pre-sentence writers.

    Enforces P5 (grade-band targeting). K-2 ch 8-10 (Drawing/Labeling/early)
    is the right audience; K-2 ch 11+ and the 3-12 book are both wrong
    audience and deprioritized.
    """
    is_k2 = _is_k2_book(chunk)

    if is_k2 and chunk.chapter_number and 8 <= chunk.chapter_number <= 10:
        return BOOST_K2_PRESENTENCE
    title = (chunk.skill_title or "").lower()
    if is_k2 and ("drawing" in title or "label" in title):
        return BOOST_K2_DRAW_LABEL_TITLE
    # P5 — K-2 sentence-era chapters are the wrong audience for pre-sentence writers.
    if is_k2 and chunk.chapter_number and chunk.chapter_number >= 11:
        return DEPRIO_K2_POST_SENTENCE
    if is_k2:
        return BOOST_K2_OTHER
    # P5 — 3-12 book is almost never relevant for EARLY_WRITER queries.
    src = (chunk.source_document or "").lower()
    if "3-12.pdf" in src or chunk.book_name == "Teal":
        return DEPRIO_WRONG_BOOK_FOR_EARLY
    return NEUTRAL


def _boost_coaching_general(chunk: RetrievedChunk) -> float:
    """COACHING_GENERAL — Brady: "always, always, always" start with Launch book.
    Overviews are NOT deprioritized here: for general coaching questions the
    overview is often a useful summary."""
    if _is_launch_book(chunk):
        return BOOST_COACHING_LAUNCH
    if _is_core_methodology(chunk):
        return BOOST_COACHING_CORE_METHODOLOGY
    if _is_episode_script(chunk):
        return BOOST_COACHING_EPISODE
    src = (chunk.source_document or "").lower()
    if "writing lessons redefined" in src or "training" in src:
        return BOOST_COACHING_TRAINING_TRANSCRIPT
    return NEUTRAL


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------


_SKILL_SEEKING_QUERY_TYPES = {
    "SCRIPTED_ML",
    "HOW_TO_TEACH",
    "TRIGGER_SPECIFIC",
    "PLAN_UNIT",
    "DEFAULT",
}


def priority_boost(
    chunk: RetrievedChunk,
    query_type: str,
    user_grade: str | None,
    writing_mode: str | None,
) -> float:
    """Return the boost multiplier for (chunk, query_type, grade, mode).

    Unknown query types fall back to the SCRIPTED_ML/HOW_TO_TEACH rule set —
    they typically involve a named skill and benefit from Launch-book-first.
    """
    band = grade_to_band(user_grade)

    if query_type == "PLAN_UNIT":
        return _boost_plan_unit(chunk, writing_mode)
    if query_type == "MANAGEMENT":
        return _boost_management(chunk)
    if query_type == "EARLY_WRITER":
        return _boost_early_writer(chunk)
    if query_type == "COACHING_GENERAL":
        return _boost_coaching_general(chunk)
    return _boost_scripted_or_how_to(chunk, band, writing_mode)


def _source_tier(
    chunk: RetrievedChunk,
    query_type: str,
    user_grade: str | None,
    writing_mode: str | None,
) -> int:
    """Assign a categorical source-priority tier (lower = higher priority).

    Brady's #1 rule: "Launch books first, always-always-always." Pure
    multiplicative boosts can be outranked by high-scoring non-Launch
    chunks (R2-H1: Essential Skills PIE beat Launch narrative MLs because
    PIE's base score was 0.65 and Launch's was 0.4 — 0.65 * 1.3 > 0.4 * 2.0).

    Tiers guarantee categorical ordering. Within a tier, the multiplicative
    boost still applies for fine-grained ordering.

    Tier 0 — PRIMARY: Launch-book scripted MLs that match mode+band
      (P1/P2 territory). Always rank above reference / taxonomy content.
    Tier 1 — HIGH: Launch-book content that's relevant (any mode or non-
      scripted) OR library-backed MLs (library is curated from Launch).
    Tier 2 — MEDIUM: Core methodology docs (Essential 2, Master 4-step,
      Think-Aloud Scripts).
    Tier 3 — LOW: Episodes, workshop transcripts, PIE scope/sequence.
    Tier 4 — FALLBACK: everything else.

    Special cases:
      * PLAN_UNIT queries: PIE doc is the canonical primary source → Tier 0.
      * MANAGEMENT queries: Launch ch 1-7 → Tier 0.
      * Overviews for skill-seeking queries → Tier 4 (deprioritize).
    """
    # Overview penalty applies for every query_type except mgmt/coaching/early-writer.
    if _applies_overview_penalty(query_type) and _is_overview_chunk(chunk):
        return 4

    # PLAN_UNIT — PIE is primary
    if query_type == "PLAN_UNIT":
        if _is_essential_skills_pie(chunk):
            return 0
        if _is_launch_book(chunk) and _is_pacing_page_chunk(chunk):
            return 1
        if _is_launch_book(chunk):
            return 1
        return 3

    # MANAGEMENT — Launch ch 1-5 (Brady's "Sections 1-5"; see _boost_management)
    if query_type == "MANAGEMENT":
        if _is_launch_book(chunk):
            ch = chunk.chapter_number or 0
            if 1 <= ch <= _MGMT_LAST_CHAPTER:
                return 0            # owns management space (boost 2.0)
            if _MGMT_LAST_CHAPTER < ch <= 13:
                return 4            # wrong audience (boost 0.4)
            return 2                # other/no-chapter Launch (boost 1.0)
        if _is_twpdms_ep11(chunk) or _is_ep1_k12(chunk):
            return 1                # relevant transcripts (boost 1.3 / 1.2)
        return 3

    # Skill-seeking queries (SCRIPTED_ML / HOW_TO_TEACH / TRIGGER_SPECIFIC /
    # COACHING_GENERAL / DEFAULT): Launch + mode match wins.
    mode_tag = _MODE_TO_TAG.get(writing_mode or "")
    launch = _is_launch_book(chunk)
    user_band = grade_to_band(user_grade)  # "3" → "3-5", "K" → "K-2", etc.

    if launch and _mode_appears_in_title(chunk, writing_mode):
        return 0  # mode-dedicated title beats everything
    if launch and mode_tag and _has_pie_tag(chunk, user_band, mode_tag):
        return 0  # Brady's primary: Launch + mode+band match
    if (
        launch
        and getattr(chunk, "is_scripted_lesson", False)
        and mode_tag
        and (getattr(chunk, "writing_mode", "") or "").lower() == (writing_mode or "").lower()
    ):
        return 0  # Launch scripted ML with matching writing_mode field
    if _is_library_source(chunk) and mode_tag and _has_pie_tag(chunk, user_band, mode_tag):
        return 0  # library-backed matches (library is curated from Launch)
    # Sink Launch ch1-7 (wrong audience for skill-seeking queries) to tier 4,
    # mirroring _boost_scripted_or_how_to's DEPRIO_WRONG_CHAPTER (0.7) — but only
    # for the query types that actually apply that boost path (see _NO_CH17_SINK).
    if (
        query_type not in _NO_CH17_SINK
        and launch and chunk.chapter_number and 1 <= chunk.chapter_number <= 7
    ):
        return 4
    if launch:
        return 1  # any other Launch content
    if _is_library_source(chunk):
        return 1
    if _is_essential_skills_pie(chunk):
        return 2  # PIE is reference material for skill-seeking, not primary
    # Core methodology
    src = (chunk.source_document or "").lower()
    if any(k in src for k in ("essential 2", "master the 4", "think-aloud scripts")):
        return 2
    if _is_episode_script(chunk):
        return 3
    return 4


def rerank(
    candidates: Iterable[RetrievedChunk],
    *,
    query_type: str,
    user_grade: str | None,
    writing_mode: str | None,
    top_k: int,
    triggered_triggers: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Re-rank hybrid-search candidates by (tier, boosted_score).

    Two-level sort: primary by source tier (Brady's source-priority rule —
    Launch-book content always ranks above reference content), secondary by
    the multiplicative priority_boost × base score (for fine-grained ordering
    within a tier).

    P6: if query-time expansion matched canonical Smekens triggers, chunks
    whose `lesson_trigger` field includes one of those triggers get an
    additional BOOST_TRIGGER_TAG_MATCH multiplier.

    The input `score` on each chunk is the RRF-fused relevance score. We
    mutate it in-place to the boosted score so downstream callers see the
    final ranking.
    """
    triggered = set(triggered_triggers or [])
    scored: list[tuple[int, float, RetrievedChunk]] = []
    for c in candidates:
        tier = _source_tier(c, query_type, user_grade, writing_mode)
        boost = priority_boost(c, query_type, user_grade, writing_mode)
        if triggered:
            chunk_triggers = set(c.lesson_trigger or [])
            if chunk_triggers & triggered:
                boost *= BOOST_TRIGGER_TAG_MATCH
                # Brady April non-negotiable #7: "If user names/asks about a
                # specific lesson from the book, don't ad lib or make it up.
                # Pull on the exact lesson already described in the book."
                #
                # The ch1-7 sink says "this section is probably irrelevant to a
                # skill query" — a HEURISTIC about relevance. The teacher naming
                # the lesson is a FACT, and the fact wins. Without this, a named
                # lesson that happens to live in ch1-7 is unreachable at ANY
                # score: measured live, "read up write down" scored 0.40 against
                # the winner's 0.25 and still landed rank 34, and ALL FOUR
                # remaining ad-libs were ch1-7 lessons.
                #
                # Guarded on the boosted value, which keeps the F18 tier/boost
                # agreement true on effective values (Launch: boost < NEUTRAL
                # iff tier 4). DEPRIO_WRONG_CHAPTER 0.7 x 1.5 = 1.05 clears it,
                # so a named ch1-7 lesson un-sinks — while a wrong-AUDIENCE
                # chunk (0.4 / 0.3 x 1.5 = 0.6 / 0.45) stays below NEUTRAL and
                # stays in tier 4. Brady's grade lock outranks his naming rule,
                # by construction rather than by a second rule.
                if tier == _TIER_CH17_SUNK and boost >= NEUTRAL:
                    tier = _TIER_OTHER_LAUNCH
        boosted = c.score * boost
        c.score = boosted
        c.source_tier = tier
        # Lower tier number = higher priority. Negate so that a single
        # descending sort picks higher-priority first.
        scored.append((-tier, boosted, c))

    # Sort: by tier DESC (so -tier means tier 0 first), then score DESC
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [c for _, _, c in scored[:top_k]]
