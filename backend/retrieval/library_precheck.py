"""Phase 7 — Scripted ML Library pre-check (Section 14 of plan).

Runs BEFORE main hybrid-search retrieval for lesson-type queries. Does
semantic matching against the library's HyDE embeddings and picks one of
four decisions based on (a) match confidence, (b) grade compatibility,
(c) query specificity.

Decisions:
  - VERBATIM_AUTO     — high-confidence specific match: bypass generation,
                        return the library's complete_ml_text verbatim
  - ASK_USER_SINGLE   — mid-confidence specific match: offer the user a
                        choice between verbatim or generated
  - SURFACE_LIST      — broad query with multiple in-grade matches: show
                        a top-3 list and let the user pick
  - SKIP              — no strong match, or query doesn't qualify:
                        fall through to main retrieval + generation

Gating (Section 14.1):
  Run ONLY for SCRIPTED_ML / TRIGGER_SPECIFIC when the user is actually
  asking for a lesson, OR for augmented follow-ups where the previous
  response was SCRIPTED_ML. Skip for HOW_TO_TEACH, PLAN_UNIT,
  COACHING_GENERAL, MANAGEMENT, EARLY_WRITER, DEFAULT.
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from handlers.citation import build_soft_citation
from retrieval.ml_library import LibraryMatch, MLLibrary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Confidence thresholds (Section 14.2) — tiered offer system
# ---------------------------------------------------------------------------
#
# Principle: the library pre-check lies on a confidence continuum. At the top
# end we return verbatim without asking (no friction when we're sure); in the
# middle we ask the teacher because the match is plausible but not obvious; at
# the bottom we skip the library entirely and generate fresh.
#
# The two thresholds below define the boundaries of those three bands:
#
#   [0.90, 1.00]   VERBATIM_AUTO   — library match is obviously the answer;
#                                    return the lesson verbatim, don't ask.
#   [0.85, 0.90)   ASK_USER_SINGLE — match is strong but not verbatim-worthy;
#                                    showing it to the teacher is useful,
#                                    but generation is also defensible.
#   [0.00, 0.85)   SKIP            — match is too weak to be worth
#                                    interrupting the user; go straight to
#                                    fresh generation.
#
# The plan originally sat ASK_USER at 0.70. That was calibrated against
# 5-template auto-HyDEs; those produced shallow matches where a 0.70 signal
# was actually informative. With hand-authored HyDEs (Phase 4 completion),
# semantic similarity is much sharper — a 0.70 match under the new regime
# is typically a tangentially-related lesson, not the intended skill.
# Showing those mid-range matches to the teacher causes false-offer friction.
#
# ASK_USER is now bounded by VERBATIM_AUTO minus a 0.05 band, giving a tight
# "ask only when we're almost certain" window. This preserves the library
# pre-check's value (catch near-verbatim matches the teacher would want) while
# avoiding the Phase-4-era false-offer problem. Same principle for the
# SURFACE_LIST (broad-query) threshold.

VERBATIM_CONFIDENCE_THRESHOLD = 0.90
# 0.05 band below verbatim — "strong match that just didn't clear the
# verbatim bar". Any wider and we interrupt the teacher with weak matches;
# any narrower and we never surface library hits for the teacher to choose.
ASK_USER_CONFIDENCE_THRESHOLD = VERBATIM_CONFIDENCE_THRESHOLD - 0.05  # 0.85
# For broad queries where we surface a LIST of candidates, we can afford
# slightly lower confidence per candidate (the teacher will pick anyway).
# Kept 0.10 below verbatim to allow a useful spread of library options.
LIST_MATCH_THRESHOLD = VERBATIM_CONFIDENCE_THRESHOLD - 0.15  # 0.75
MIN_LIST_MATCHES = 2
TOP_K_CANDIDATES = 5


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------


class PrecheckDecision(str, enum.Enum):
    VERBATIM_AUTO = "verbatim_auto"
    ASK_USER_SINGLE = "ask_user_single"
    SURFACE_LIST = "surface_list"
    SKIP = "skip"


@dataclass
class PrecheckResult:
    decision: PrecheckDecision
    # For VERBATIM_AUTO / ASK_USER_SINGLE: the single best match
    best_match: Optional[LibraryMatch] = None
    # For SURFACE_LIST: the top-3 in-grade matches
    candidates: list[LibraryMatch] = field(default_factory=list)
    # Raw top-5 from the library (pre-filter), useful for logging
    all_candidates: list[LibraryMatch] = field(default_factory=list)
    query_specificity: str = "broad"


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


_LESSON_QUERY_TYPES = {"SCRIPTED_ML", "TRIGGER_SPECIFIC"}


def should_run_precheck(
    query_type: str,
    last_response_type: Optional[str] = None,
) -> bool:
    """Section 14.1 gating rule.

    Primary: query_type ∈ {SCRIPTED_ML, TRIGGER_SPECIFIC} — the user is
    asking for a lesson.

    Secondary: the previous response was SCRIPTED_ML and we're continuing
    the lesson flow (augmented follow-up like "now adapt for 6th grade").

    Skipped for HOW_TO_TEACH, PLAN_UNIT, COACHING_GENERAL, MANAGEMENT,
    EARLY_WRITER, DEFAULT — these should go through main retrieval.
    """
    if query_type in _LESSON_QUERY_TYPES:
        return True
    # Augmented follow-up that continues a prior SCRIPTED_ML
    if last_response_type == "SCRIPTED_ML" and query_type in _LESSON_QUERY_TYPES:
        return True
    return False


# ---------------------------------------------------------------------------
# Pre-check execution
# ---------------------------------------------------------------------------


def library_precheck(
    library: MLLibrary,
    query_embedding: list[float],
    user_grade: Optional[str],
    query_specificity: str,
    user_skill_phrase: Optional[str] = None,
    user_writing_mode: Optional[str] = None,
) -> PrecheckResult:
    """Run the HyDE match + decision logic.

    Args:
        library: loaded MLLibrary with embedding index built.
        query_embedding: dense vector of the user's query.
        user_grade: concrete grade ("K", "3", etc.) or None.
        query_specificity: "specific" or "broad" — from QU Phase 5.
        user_skill_phrase: the teacher's own naming of the skill (from QU's
            ``strategy_name``). When the matched library entry's title shares
            no content words with this phrase, ``ASK_USER_SINGLE`` is demoted
            to ``SKIP`` — offering "verbatim or generate?" on a wrong-titled
            entry would confuse the teacher and waste a turn.
        user_writing_mode: QU-extracted writing mode ("Persuade" / "Inform" /
            "Narrate"). Used by the broad-query metadata fallback to catalog
            candidate lessons by mode when embedding similarity doesn't find
            enough matches — generic queries like "Give me a persuasive
            lesson for 5th grade" don't semantically match any ONE skill's
            HyDEs but DO match a writing-mode category structurally.

    Structurally-broad queries:
        When ``user_skill_phrase`` is absent, the query is treated as broad
        even if QU labeled it "specific". A SCRIPTED_ML request with mode +
        grade but no skill name is a catalog-browse intent — Brady's B-R05
        ("scan chapters 8-13 for P lessons and suggest those"). We honor
        semantics, not QU's label.
    """
    # Filter by grade BEFORE truncating (recert B3). This used to take the
    # GLOBAL top-K and then filter, which silently wasted the pool: Brady's 24
    # MLs are grade-parallel ('Determine the strongest side' has 12 entries —
    # K,1,2,3,4,5 x day1/day2), so the OUT-of-grade copies of the very lesson
    # the teacher named consumed every slot, and the filter then threw them all
    # away. Measured live on realistic named asks (campaign/recert/
    # probe_sibling_crowding.py): out-grade siblings took 4 of 5 slots on
    # almost every probe; the in-grade pool's median size was 1, so separation
    # was UNDEFINED on 12/18; and a grade-K ask for a lesson that EXISTS at
    # grade K came back EMPTY -> SKIP -> the LLM ad-libs a named lesson
    # (April non-neg #7). find_best_in_grade over-fetches, filters, then
    # truncates: undefined separation 12/18 -> 0/18, median pool 1 -> 4.
    #
    # `all_candidates` keeps the unfiltered global view — it is the debug/
    # inspection field, and narrowing it would hide exactly the crowding this
    # fix addresses.
    all_candidates = library.find_matches(
        query_embedding, user_grade=user_grade, top_k=TOP_K_CANDIDATES
    )
    in_grade = library.find_best_in_grade(
        query_embedding, user_grade=user_grade, top_k=TOP_K_CANDIDATES
    )
    top5 = all_candidates

    # Semantic correction: a "specific" query without a skill name is
    # structurally broad. QU can misfire here (e.g. "Give me a persuasive
    # lesson for 5th grade" — mode is named, no skill). Trust the
    # skill-name presence over QU's binary label.
    effective_specificity = query_specificity
    if effective_specificity == "specific" and not (user_skill_phrase or "").strip():
        effective_specificity = "broad"
        logger.info(
            "precheck: overriding specificity specific→broad (no user_skill_phrase)"
        )

    if effective_specificity == "specific":
        decision, best = _decide_specific(in_grade, user_skill_phrase, user_writing_mode)
        return PrecheckResult(
            decision=decision,
            best_match=best,
            all_candidates=top5,
            query_specificity=effective_specificity,
        )

    # --- BROAD ---------------------------------------------------------------
    # Two paths, in priority order:
    #   1. Semantic similarity (HyDE match ≥ LIST_MATCH_THRESHOLD). Works when
    #      the query has enough specificity to match individual skills.
    #   2. Metadata catalog fallback. When semantic similarity doesn't produce
    #      MIN_LIST_MATCHES qualifying candidates, browse by writing_mode +
    #      grade — that's the intent for queries like "give me a persuasive
    #      lesson for 5th grade".
    qualifying = [m for m in in_grade if m.confidence >= LIST_MATCH_THRESHOLD]
    if len(qualifying) >= MIN_LIST_MATCHES:
        return PrecheckResult(
            decision=PrecheckDecision.SURFACE_LIST,
            candidates=qualifying[:3],
            all_candidates=top5,
            query_specificity=effective_specificity,
        )

    metadata_candidates = _catalog_by_metadata(
        library, user_grade=user_grade, user_writing_mode=user_writing_mode,
    )
    if len(metadata_candidates) >= MIN_LIST_MATCHES:
        return PrecheckResult(
            decision=PrecheckDecision.SURFACE_LIST,
            candidates=metadata_candidates[:3],
            all_candidates=top5,
            query_specificity=effective_specificity,
        )

    return PrecheckResult(
        decision=PrecheckDecision.SKIP,
        all_candidates=top5,
        query_specificity=effective_specificity,
    )


def _catalog_by_metadata(
    library: MLLibrary,
    *,
    user_grade: Optional[str],
    user_writing_mode: Optional[str],
) -> list[LibraryMatch]:
    """Browse the library structurally when embedding matching didn't suffice.

    Returns ``LibraryMatch`` objects (with synthetic confidence 1.0) so the
    response builder can treat them the same as semantic matches. The mode
    filter is required — without it, "give me a lesson for 5th grade" would
    surface arbitrary 5th-grade entries regardless of topic. If neither
    ``user_grade`` nor ``user_writing_mode`` is present, returns empty (the
    caller then falls to SKIP → §14.8 read-before-ask).
    """
    if not user_writing_mode:
        return []

    from retrieval.ml_library import LibraryMatch, is_grade_compatible

    mode_token = user_writing_mode.strip().lower()
    results: list[LibraryMatch] = []
    for entry in library.entries:
        # writing_modes is stored as ["Persuade", "Inform"] etc.
        if not any(mode_token == m.strip().lower() for m in (entry.writing_modes or [])):
            continue
        grade_ok = (
            True
            if not user_grade
            else is_grade_compatible(entry.grade_levels, user_grade)
        )
        if not grade_ok:
            continue
        # Synthetic high confidence — these are metadata-filtered, not semantic
        # matches, so we don't rank them by similarity. The list order follows
        # library insertion order (typically pedagogical sequence).
        results.append(LibraryMatch(
            entry=entry,
            confidence=1.0,
            matched_hyde="(metadata-filtered)",
            grade_compatible=True,
        ))
    return results


# Words that appear in nearly every "give me a scripted ML on X for grade Y"
# query and so add no signal when comparing user vocab against an entry title.
_VOCAB_STOPWORDS: frozenset[str] = frozenset({
    "give", "show", "create", "make", "write", "scripted", "mini", "lesson",
    "minilesson", "ml", "for", "the", "a", "an", "and", "or", "to", "of",
    "in", "on", "with", "about", "grade", "graders", "grader", "students",
    "student", "kids", "class", "please", "want", "need", "help", "use",
    "using", "teach", "teaching", "learn", "learning", "kindergarten",
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "eleventh", "twelfth", "k2", "k", "k-2",
})


def _vocab_overlap(user_phrase: Optional[str], entry_title: str) -> bool:
    """True when user's content words intersect the entry title's content words.

    "Content words" = lowercase ≥4-char tokens minus stopwords. Used as a
    sanity gate on ``ASK_USER_SINGLE``: a high-confidence semantic match whose
    title shares zero vocabulary with the teacher's phrasing is almost always
    the wrong skill — offering "verbatim or generate?" on it just creates
    confusion about why the suggested title is unrelated.
    """
    if not user_phrase or not entry_title:
        return True  # no phrase to compare → don't gate on this
    def _content_words(text: str) -> set[str]:
        return {
            w for w in re.findall(r"[a-zA-Z]+", text.lower())
            if len(w) >= 4 and w not in _VOCAB_STOPWORDS
        }
    user_words = _content_words(user_phrase)
    if not user_words:
        return True  # nothing to gate on
    return bool(user_words & _content_words(entry_title))


def _mode_compatible(
    user_writing_mode: Optional[str], entry_writing_modes: list[str]
) -> bool:
    """True when the entry's writing-mode tag doesn't conflict with the user's.

    Sanity gate on ``VERBATIM_AUTO`` (audit finding V2): a high-confidence
    match tagged for a different writing mode than the teacher asked for is the
    wrong *piece type* (e.g. an Inform-only entry for a Persuade request), and
    auto-shipping it verbatim would be wrong.

    Deliberately permissive — it only reports INCOMPATIBLE (returns False) when
    there is real conflicting evidence, so it never blocks on absent data:
      - entry has NO ``writing_modes`` tag (~61% of the library) → compatible
      - user's mode is unknown (None/empty) → compatible
      - user's mode is "all" (mode-agnostic) → compatible with anything
      - entry is tagged "all" (applies to every mode) → compatible
      - otherwise: compatible iff the user's mode is among the entry's tags
    All comparisons are case-insensitive, matching ``_catalog_by_metadata``.
    """
    entry_modes = [m.strip().lower() for m in (entry_writing_modes or [])]
    if not entry_modes:
        return True  # untagged entry — nothing to conflict with
    user_mode = (user_writing_mode or "").strip().lower()
    if not user_mode or user_mode == "all":
        return True  # unknown / mode-agnostic — don't block
    if "all" in entry_modes:
        return True  # entry applies to every mode
    return user_mode in entry_modes


def _decide_specific(
    in_grade: list[LibraryMatch],
    user_skill_phrase: Optional[str] = None,
    user_writing_mode: Optional[str] = None,
) -> tuple[PrecheckDecision, Optional[LibraryMatch]]:
    if not in_grade:
        return PrecheckDecision.SKIP, None
    best = in_grade[0]
    if best.confidence >= VERBATIM_CONFIDENCE_THRESHOLD:
        # Data-quality guards (audit findings V1 + V2): a top-band confidence
        # score is necessary but NOT sufficient to ship a lesson verbatim.
        # Two cheap deterministic sanity checks must also hold, or we fall
        # through to the weaker decisions below (never auto-ship a mismatched
        # lesson — same fall-through the ASK_USER vocab gate already uses):
        #
        #   V1 vocab — the entry title must share a content word with the
        #     teacher's own phrasing. Reuses the ASK_USER vocab gate; a
        #     disjoint-vocab match is the wrong skill even at 0.95.
        #   V2 mode  — if the entry is TAGGED with writing_modes AND the user's
        #     mode is known, the user's mode must be compatible. A wrong-mode
        #     lesson (e.g. an Inform-only entry for a Persuade request) is the
        #     wrong piece type. NO-OP when the entry is untagged (~61% of the
        #     library) or the mode is unknown / mode-agnostic ("all") — we must
        #     not block a verbatim match on absent data.
        vocab_ok = _vocab_overlap(user_skill_phrase, best.entry.skill_title)
        mode_ok = _mode_compatible(user_writing_mode, best.entry.writing_modes)
        if vocab_ok and mode_ok:
            return PrecheckDecision.VERBATIM_AUTO, best
        logger.info(
            "VERBATIM_AUTO gated (vocab_ok=%s, mode_ok=%s) — best entry %r "
            "vs user phrase %r / mode %r; falling through to weaker decision",
            vocab_ok, mode_ok, best.entry.skill_title, user_skill_phrase,
            user_writing_mode,
        )
        # fall through to the weaker (ASK_USER / SKIP) decisions below.
    if best.confidence >= ASK_USER_CONFIDENCE_THRESHOLD:
        # Vocab gate: an "ask the teacher" prompt only makes sense if the
        # offered library entry plausibly addresses the same skill the teacher
        # named. When the title shares no content words with the user's
        # phrasing, the verbatim option is on the wrong topic — demote to
        # SKIP and let generation handle it on the teacher's vocabulary.
        if not _vocab_overlap(user_skill_phrase, best.entry.skill_title):
            logger.info(
                "ASK_USER demoted to SKIP — best library entry "
                "%r does not share vocab with user phrase %r",
                best.entry.skill_title,
                user_skill_phrase,
            )
            return PrecheckDecision.SKIP, None
        return PrecheckDecision.ASK_USER_SINGLE, best
    return PrecheckDecision.SKIP, None


# ---------------------------------------------------------------------------
# Response builders (Section 14.4, 14.5, 14.6)
# ---------------------------------------------------------------------------


def build_verbatim_response(match: LibraryMatch, user_query_skill_phrase: Optional[str] = None) -> str:
    """Format a library entry for verbatim return, preserving user vocabulary.

    Brady Fm5: the book pointer is the soft conditional form with the FULL title,
    built deterministically from the entry's structured page + resolved title —
    never the internal "Teal book"/"K-2 book" shorthand in entry.book_reference.

    Brady E7 (07:30): the delivered verbatim text renders the ML body in 4-step
    block shape (Fm2 — Step headers on their own blocks, never one glued
    paragraph) and ENDS with the E2 customization close, exactly like the
    generated SCRIPTED_ML path. Both are pure string assembly here — the
    verbatim path deliberately BYPASSES the scrubber + generation loop.

    Order: preface → 4-step body → soft citation → E2 close (E2 LAST, matching
    the generated path where the customization close is the final paragraph).

    Reuses the SINGLE-SOURCE helpers rather than re-deriving either:
      * ``handlers._base_text._blockify_steps`` — the SAME shared Fm2 blockifier
        the generated + markdown paths run. Idempotent and a no-op on the
        already-block-shaped stored ML text (the real library entries carry
        their own \\n\\n paragraph breaks); it only inserts a break before a
        glued capitalized "Step N" header, so it guarantees the block-shape
        invariant without imposing a step structure the stored prose may lack.
      * ``handlers.scripted_ml._E2_FOLLOWUP`` — the ONE E2 close string, so the
        verbatim + generated deliveries can never drift.
    Both are FUNCTION-LOCAL imports (cycle-safe): the handlers package imports
    retrieval heavily (handlers.scripted_ml imports this module function-locally),
    and pulling _E2_FOLLOWUP would otherwise eagerly load the whole generation
    stack. Mirrors the lazy-import pattern already used in
    ``_resolve_full_book_title`` / ``_catalog_by_metadata`` below.
    """
    from handlers._base_text import _blockify_steps
    from handlers.scripted_ml import _E2_FOLLOWUP

    entry = match.entry
    if user_query_skill_phrase and _phrases_differ(user_query_skill_phrase, entry.skill_title):
        preface = (
            f"Here's the Smekens scripted ML on {user_query_skill_phrase} "
            f"(titled '{entry.skill_title}'):"
        )
    else:
        preface = f"Here's the Smekens scripted ML on {entry.skill_title}:"

    # Fm2: guarantee the body renders in paragraph blocks (glued "Step N"
    # headers pushed onto their own block); no-op on already-blocked prose.
    body = _blockify_steps(entry.complete_ml_text.strip())
    citation = build_soft_citation(_resolve_full_book_title(entry), _entry_page(entry))
    parts = [preface, body]
    if citation:
        parts.append(citation)
    # E2 customization close — always last (unconditional, unlike the citation).
    parts.append(_E2_FOLLOWUP)
    return "\n\n".join(parts)


def _resolve_full_book_title(entry) -> Optional[str]:
    """Full teacher-facing title from a library entry — never the shorthand.
    Detects the book from the shorthand in book_reference, else strips a .pdf
    off source_document.

    The canonical title lives in ONE place — ``assembler._BOOK_FULL_TITLE``.
    Lazy-imported (cycle-safe) so a demo reword of the Fm5 citation wording
    can't silently diverge from the title the rest of the app cites."""
    from retrieval.assembler import _BOOK_FULL_TITLE  # single source of truth for the canonical title
    ref = (entry.book_reference or "").lower()
    if "teal" in ref or "3-12" in ref or "3–12" in ref:
        return _BOOK_FULL_TITLE["Teal"]
    if "k-2" in ref or "k2" in ref:
        return _BOOK_FULL_TITLE["K-2"]
    src = entry.source_document or ""
    if src.startswith("Launching the Writers Workshop"):
        return src[:-4] if src.lower().endswith(".pdf") else src
    return None


def _entry_page(entry) -> Optional[int]:
    """Clean page number — prefer the typed field, regex-fallback the reference."""
    if entry.page_number is not None:
        return entry.page_number
    m = re.search(r"\bp\.?\s*(\d+)", entry.book_reference or "", re.IGNORECASE)
    return int(m.group(1)) if m else None


def build_ask_user_message(
    match: LibraryMatch,
    user_query_skill_phrase: Optional[str] = None,
) -> str:
    """Section 14.2: mid-confidence offer.

    Includes the Launch-book citation in the expected form ("page N" plus a
    "digital resources" reminder) so downstream consumers don't have to dig
    it out of the book_reference string. Also honors the teacher's own
    vocabulary when it differs from the library's internal skill title.
    """
    entry = match.entry
    # Prefer the teacher's phrasing if it differs from the library title.
    if user_query_skill_phrase and _phrases_differ(user_query_skill_phrase, entry.skill_title):
        skill_phrase = (
            f"'{user_query_skill_phrase}' (titled '{entry.skill_title}' in the book)"
        )
    else:
        skill_phrase = f"'{entry.skill_title}'"

    # Expand "p. 64" → "page 64" so the response carries the explicit
    # "page N" token Brady cites in her book-citation rule.
    ref = entry.book_reference or ""
    if ref:
        ref = re.sub(r"\bp\.\s*(\d+)\b", r"page \1", ref)
    citation = (
        f" It's covered in the {ref}. You can also find the graphic "
        f"organizer in the book's digital resources."
        if ref else ""
    )

    return (
        f"I have a Smekens scripted ML on {skill_phrase}.{citation} "
        "Want the verbatim version, or should I generate one based on the framework?"
    )


def build_surface_list_message(candidates: list[LibraryMatch]) -> str:
    """Section 14.2 BROAD: top-3 skill list."""
    lines = ["I have these Smekens scripted MLs that match:"]
    for i, m in enumerate(candidates, 1):
        ref = m.entry.book_reference or "—"
        lines.append(f"  {i}. {m.entry.skill_title} (from {ref})")
    lines.append("")
    lines.append("Which one would you like?")
    return "\n".join(lines)


def _phrases_differ(user_phrase: str, entry_title: str) -> bool:
    """True if the user's phrasing doesn't obviously map to the entry title."""
    u = user_phrase.lower().strip()
    t = entry_title.lower().strip()
    if not u or not t:
        return False
    return u != t and u not in t and t not in u
