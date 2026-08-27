"""Unit tests for Phase 7 library pre-check (Section 14 of plan).

Covers:
  - should_run_precheck() gating across all query types (14.1)
  - library_precheck() decision tree for SPECIFIC × (VERBATIM/ASK_USER/SKIP) (14.2)
  - library_precheck() decision tree for BROAD × (SURFACE_LIST/SKIP) (14.2)
  - Grade compatibility filter removes out-of-band matches (14.3)
  - Response-builder vocab preservation (14.6)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from retrieval.library_precheck import (
    ASK_USER_CONFIDENCE_THRESHOLD,
    LIST_MATCH_THRESHOLD,
    MIN_LIST_MATCHES,
    PrecheckDecision,
    VERBATIM_CONFIDENCE_THRESHOLD,
    build_ask_user_message,
    build_surface_list_message,
    build_verbatim_response,
    library_precheck,
    should_run_precheck,
)
from retrieval.ml_library import LibraryEntry, LibraryMatch, MLLibrary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _entry(
    ml_id: str,
    skill_title: str,
    grade_levels: list[str] | None = None,
    book_reference: str = "Teal book p. 64",
    writing_modes: list[str] | None = None,
) -> LibraryEntry:
    return LibraryEntry(
        ml_id=ml_id,
        skill_title=skill_title,
        hyde_summaries=[f"How do I teach {skill_title}?"],
        grade_levels=grade_levels or ["3-5", "6-8", "9-12"],
        # ``is not None`` (not ``or``) so an explicit ``[]`` yields an
        # UNTAGGED entry — the ~61% of the real library with no writing_modes.
        writing_modes=writing_modes if writing_modes is not None else ["Inform", "Persuade"],
        pie_tags=["I", "P"],
        pie_tags_by_band={"3-5": ["I", "P"], "6-8": ["I", "P"]},
        lesson_triggers=[],
        book_reference=book_reference,
        page_number=64,
        source_document="Launching the Writers Workshop 3-12.pdf",
        source_chunk_id=f"chunk-{ml_id}",
        complete_ml_text="Step 1 — Introduce the skill. " * 30,
        priority_tier=1,
    )


@pytest.fixture
def library() -> MLLibrary:
    entries = [
        _entry("lib-pizza", "Pizza table strategy"),
        _entry("lib-snapple", "Snapple details"),
        _entry("lib-transitions", "Transitions within paragraphs"),
        _entry("lib-k2-draw", "Add drawing details", grade_levels=["K-2"]),
    ]
    return MLLibrary(entries)


def _match(
    entry: LibraryEntry,
    confidence: float,
    grade_compatible: bool = True,
) -> LibraryMatch:
    return LibraryMatch(
        entry=entry,
        confidence=confidence,
        matched_hyde=entry.hyde_summaries[0],
        grade_compatible=grade_compatible,
    )


# ---------------------------------------------------------------------------
# Gating — should_run_precheck (Section 14.1)
# ---------------------------------------------------------------------------


class TestShouldRunPrecheck:
    @pytest.mark.parametrize("qt,expected", [
        ("SCRIPTED_ML", True),
        ("TRIGGER_SPECIFIC", True),
        ("HOW_TO_TEACH", False),
        ("PLAN_UNIT", False),
        ("COACHING_GENERAL", False),
        ("MANAGEMENT", False),
        ("EARLY_WRITER", False),
        ("DEFAULT", False),
    ])
    def test_gating_per_query_type(self, qt, expected):
        assert should_run_precheck(qt) is expected

    def test_augmented_after_scripted_still_runs(self):
        """Section 14.1 secondary rule: augmented follow-up to SCRIPTED_ML."""
        assert should_run_precheck("SCRIPTED_ML", last_response_type="SCRIPTED_ML") is True

    def test_augmented_after_coaching_does_not_run(self):
        assert should_run_precheck("COACHING_GENERAL", last_response_type="SCRIPTED_ML") is False


# ---------------------------------------------------------------------------
# Decision tree — SPECIFIC (Section 14.2)
# ---------------------------------------------------------------------------


class TestSpecificDecision:
    """Specific-path tests. Every test passes ``user_skill_phrase`` — the
    new (Phase 12) invariant is that a "specific" query MUST have a named
    skill; without one, the precheck overrides specificity to broad."""

    # A skill phrase that actually overlaps one of the fixture titles so the
    # vocab gate doesn't demote ASK_USER_SINGLE — kept constant for all tests.
    _SKILL = "Pizza table"

    def test_high_confidence_verbatim_auto(self, library):
        fake = [_match(library.entries[0], 0.95)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._SKILL,
            )
        assert result.decision is PrecheckDecision.VERBATIM_AUTO
        assert result.best_match.entry.ml_id == "lib-pizza"

    def test_exact_verbatim_threshold_triggers_verbatim(self, library):
        """Boundary: confidence == 0.90 → VERBATIM_AUTO (inclusive)."""
        fake = [_match(library.entries[0], VERBATIM_CONFIDENCE_THRESHOLD)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._SKILL,
            )
        assert result.decision is PrecheckDecision.VERBATIM_AUTO

    def test_mid_confidence_ask_user(self, library):
        # 0.87 is between ASK_USER_CONFIDENCE_THRESHOLD (0.85) and
        # VERBATIM_CONFIDENCE_THRESHOLD (0.90).
        fake = [_match(library.entries[0], 0.87)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._SKILL,
            )
        assert result.decision is PrecheckDecision.ASK_USER_SINGLE
        assert result.best_match is not None

    def test_below_ask_user_threshold_skips(self, library):
        # 0.80 was ASK_USER before the threshold tightening; now it must SKIP.
        fake = [_match(library.entries[0], 0.80)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._SKILL,
            )
        assert result.decision is PrecheckDecision.SKIP

    def test_exact_ask_user_threshold_triggers_ask(self, library):
        fake = [_match(library.entries[0], ASK_USER_CONFIDENCE_THRESHOLD)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._SKILL,
            )
        assert result.decision is PrecheckDecision.ASK_USER_SINGLE

    def test_low_confidence_skip(self, library):
        fake = [_match(library.entries[0], 0.65)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._SKILL,
            )
        assert result.decision is PrecheckDecision.SKIP
        assert result.best_match is None

    def test_high_confidence_but_out_of_grade_skip(self, library):
        """Even 0.95 match must be dropped if grade-incompatible."""
        fake = [_match(library.entries[0], 0.95, grade_compatible=False)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._SKILL,
            )
        assert result.decision is PrecheckDecision.SKIP

    def test_no_matches_at_all_skip(self, library):
        with patch.object(library, "find_matches", return_value=[]):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._SKILL,
            )
        assert result.decision is PrecheckDecision.SKIP

    def test_ask_user_demoted_when_title_shares_no_user_vocab(self, library):
        """ASK_USER_SINGLE on a wrong-titled match wastes a turn — SKIP instead.

        User asked for "topic sentence and supporting details"; the closest
        library entry is "Pizza table strategy" (semantic neighbor, but no
        shared content words). Offering "verbatim or generate?" on the wrong
        title would confuse the teacher.
        """
        fake = [_match(library.entries[0], 0.87)]  # ASK_USER band
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase="topic sentence and supporting details",
            )
        assert result.decision is PrecheckDecision.SKIP

    def test_ask_user_kept_when_title_shares_user_vocab(self, library):
        """ASK_USER_SINGLE survives when user's vocabulary actually overlaps."""
        fake = [_match(library.entries[0], 0.87)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase="pizza table for paragraph structure",
            )
        assert result.decision is PrecheckDecision.ASK_USER_SINGLE

    def test_no_skill_phrase_overrides_to_broad_not_ask_user(self, library):
        """Phase 12 invariant (replaces prior test): a "specific" query with
        no named skill is structurally broad. Single ASK_USER_SINGLE offers
        only make sense when the teacher told us what skill they want — a
        0.87-confidence match on an unnamed query is just a guess.

        Previously the system would offer "verbatim or generate?" for that
        match, which produced wrong-topic offers (see TS08 in the session
        suite). The override to broad + metadata catalog path is the correct
        behavior."""
        fake = [_match(library.entries[0], 0.87)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=None,
            )
        assert result.decision is not PrecheckDecision.ASK_USER_SINGLE
        assert result.query_specificity == "broad"  # override applied

    def test_verbatim_demoted_when_vocab_disjoint(self, library):
        """Audit finding V1: the vocab gate now ALSO guards VERBATIM_AUTO.

        A ≥0.90 semantic match whose title shares no content words with the
        teacher's own phrasing is almost always the wrong skill — auto-shipping
        it verbatim was the latent defect. It must fall through the weaker
        decisions (ASK_USER also gates vocab) to SKIP.

        (This test previously asserted the OPPOSITE — that the gate affected
        only ASK_USER — which locked in the V1 defect.)
        """
        fake = [_match(library.entries[0], 0.95)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase="topic sentence and supporting details",
            )
        assert result.decision is not PrecheckDecision.VERBATIM_AUTO
        assert result.decision is PrecheckDecision.SKIP

    def test_specificity_override_to_broad_when_no_skill_phrase(self, library):
        """Phase 12 fix (TS16): QU sometimes labels 'Give me a persuasive
        lesson for 5th grade' as specificity='specific' even though no skill
        is named. The precheck treats missing user_skill_phrase as the ground
        truth — structurally broad."""
        # No matches to force the broad-path fallbacks
        with patch.object(library, "find_matches", return_value=[]):
            result = library_precheck(
                library, [0.1] * 4, "5", "specific",
                user_skill_phrase=None,  # no skill named
                user_writing_mode="Inform",
            )
        # Overridden to broad. With mode=Inform, the metadata path activates;
        # our fixture library has entries tagged ["Inform", "Persuade"], so
        # at least MIN_LIST_MATCHES qualify.
        assert result.query_specificity == "broad"


# ---------------------------------------------------------------------------
# VERBATIM_AUTO data-quality guards — audit findings V1 (vocab) + V2 (mode)
# ---------------------------------------------------------------------------


class TestVerbatimAutoGuards:
    """A top-band (≥0.90) confidence score is necessary but NOT sufficient to
    ship a library lesson verbatim. Two cheap deterministic sanity checks must
    also hold, or the decision falls through to the weaker branches (never
    auto-ship a mismatched lesson):

      V1 vocab — the entry title must share a content word with the teacher's
                 own phrasing (reuses the existing ASK_USER vocab gate).
      V2 mode  — if the entry is TAGGED with writing_modes AND the user's mode
                 is known, the user's mode must be compatible. NO-OP when the
                 entry is untagged (~61% of the library) or the mode is unknown
                 / mode-agnostic ("all").
    """

    _OVERLAP = "Pizza table"  # shares content words with 'Pizza table strategy'
    _DISJOINT = "topic sentence and supporting details"  # shares nothing

    # ---- V2: writing-mode gate on the VERBATIM_AUTO branch --------------
    def test_verbatim_gated_when_mode_incompatible(self, library):
        """(b) ≥0.90 match on a TAGGED entry whose modes exclude the user's
        stated mode must NOT ship verbatim (wrong piece type). Vocab overlaps
        here, so the mode gate is provably the ONLY thing stopping verbatim."""
        # fixture entry is tagged ["Inform", "Persuade"]; teacher wants Entertain.
        fake = [_match(library.entries[0], 0.95)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._OVERLAP,
                user_writing_mode="Entertain",
            )
        assert result.decision is not PrecheckDecision.VERBATIM_AUTO

    def test_verbatim_stands_when_mode_compatible(self, library):
        """(c) no-regression: overlapping vocab + a mode the entry supports
        ("Inform" ∈ ["Inform","Persuade"]) → still VERBATIM_AUTO."""
        fake = [_match(library.entries[0], 0.95)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._OVERLAP,
                user_writing_mode="Inform",
            )
        assert result.decision is PrecheckDecision.VERBATIM_AUTO

    # ---- V2 no-ops (must NOT block) ------------------------------------
    def test_verbatim_not_blocked_when_mode_agnostic_all(self, library):
        """V2 no-op: mode "all" is mode-agnostic (e.g. "give me a lesson on
        transitions" — a named skill, no stated mode). It reaches this path
        as the string "all" and must be treated as a wildcard, never as an
        incompatible token. Naive membership would wrongly demote it."""
        fake = [_match(library.entries[0], 0.95)]  # tagged ["Inform","Persuade"]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._OVERLAP,
                user_writing_mode="all",
            )
        assert result.decision is PrecheckDecision.VERBATIM_AUTO

    def test_verbatim_not_blocked_when_entry_untagged(self, library):
        """V2 no-op: ~61% of the real library has NO writing_modes tag. An
        otherwise-incompatible user mode must not block those — there is
        nothing to be incompatible WITH."""
        untagged = _entry("lib-untagged", "Pizza table deep dive", writing_modes=[])
        fake = [_match(untagged, 0.95)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._OVERLAP,
                user_writing_mode="Entertain",  # would be incompatible IF tagged
            )
        assert result.decision is PrecheckDecision.VERBATIM_AUTO

    def test_verbatim_not_blocked_when_mode_unknown(self, library):
        """V2 no-op: user mode unknown (None) → mode gate is inert; the entry's
        tag is irrelevant. Overlapping vocab → VERBATIM_AUTO (unchanged)."""
        fake = [_match(library.entries[0], 0.95)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._OVERLAP,
                user_writing_mode=None,
            )
        assert result.decision is PrecheckDecision.VERBATIM_AUTO

    # ---- V1 + V2 together ----------------------------------------------
    def test_verbatim_gated_when_both_vocab_and_mode_fail(self, library):
        """Both guards failing → definitely not verbatim; lands on SKIP
        (disjoint vocab also fails the downstream ASK_USER vocab gate)."""
        fake = [_match(library.entries[0], 0.95)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "specific",
                user_skill_phrase=self._DISJOINT,
                user_writing_mode="Entertain",
            )
        assert result.decision is not PrecheckDecision.VERBATIM_AUTO
        assert result.decision is PrecheckDecision.SKIP


# ---------------------------------------------------------------------------
# Broad-query metadata catalog path (Phase 12, TS16)
# ---------------------------------------------------------------------------


class TestMetadataCatalogPath:
    def test_broad_with_mode_returns_surface_list_from_metadata(self, library):
        """When embedding similarity fails to produce MIN_LIST_MATCHES but the
        library has entries matching the mode + grade, surface them via the
        metadata path."""
        # Force empty semantic matches so only the metadata path can fire
        with patch.object(library, "find_matches", return_value=[]):
            result = library_precheck(
                library, [0.1] * 4, "4", "broad",
                user_skill_phrase=None,
                user_writing_mode="Inform",
            )
        assert result.decision is PrecheckDecision.SURFACE_LIST
        assert len(result.candidates) >= MIN_LIST_MATCHES
        # Each must have Inform in its writing_modes
        for match in result.candidates:
            assert any(m.lower() == "inform" for m in match.entry.writing_modes)

    def test_broad_without_mode_falls_to_skip(self, library):
        """No mode filter = can't meaningfully browse. Fall through to SKIP
        (then §14.8 read-before-ask asks for more info)."""
        with patch.object(library, "find_matches", return_value=[]):
            result = library_precheck(
                library, [0.1] * 4, "4", "broad",
                user_skill_phrase=None,
                user_writing_mode=None,
            )
        assert result.decision is PrecheckDecision.SKIP

    def test_semantic_path_takes_priority_over_metadata(self, library):
        """When semantic matches ≥ MIN_LIST_MATCHES, use them (they're more
        relevant than a whole-catalog browse). Metadata only fires on
        insufficient semantic matches."""
        fake = [
            _match(library.entries[0], 0.80),
            _match(library.entries[1], 0.78),
        ]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(
                library, [0.1] * 4, "4", "broad",
                user_skill_phrase=None,
                user_writing_mode="Inform",
            )
        assert result.decision is PrecheckDecision.SURFACE_LIST
        # Semantic candidates used, not metadata (confidence 0.80, not 1.0)
        confidences = [c.confidence for c in result.candidates]
        assert any(c < 1.0 for c in confidences)

    def test_metadata_path_respects_grade_filter(self, library):
        """A 4th-grade query should only surface entries compatible with grade 4."""
        with patch.object(library, "find_matches", return_value=[]):
            result = library_precheck(
                library, [0.1] * 4, "4", "broad",
                user_skill_phrase=None,
                user_writing_mode="Inform",
            )
        if result.decision is PrecheckDecision.SURFACE_LIST:
            # Fixture's K-2-only entry ('lib-k2-draw') must not appear for grade 4
            titles = [c.entry.ml_id for c in result.candidates]
            assert "lib-k2-draw" not in titles


# ---------------------------------------------------------------------------
# Decision tree — BROAD (Section 14.2)
# ---------------------------------------------------------------------------


class TestBroadDecision:
    def test_two_qualifying_matches_surface_list(self, library):
        fake = [
            _match(library.entries[0], 0.85),
            _match(library.entries[1], 0.75),
            _match(library.entries[2], 0.55),  # below threshold, excluded
        ]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(library, [0.1] * 4, "4", "broad")
        assert result.decision is PrecheckDecision.SURFACE_LIST
        assert len(result.candidates) == 2
        assert {m.entry.ml_id for m in result.candidates} == {"lib-pizza", "lib-snapple"}

    def test_surface_list_caps_at_three(self, library):
        fake = [_match(library.entries[i], 0.85 - 0.01 * i) for i in range(4)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(library, [0.1] * 4, "4", "broad")
        assert result.decision is PrecheckDecision.SURFACE_LIST
        assert len(result.candidates) == 3

    def test_single_match_below_minimum_skip(self, library):
        """MIN_LIST_MATCHES = 2 — one qualifying match isn't enough."""
        assert MIN_LIST_MATCHES == 2
        fake = [_match(library.entries[0], 0.85)]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(library, [0.1] * 4, "4", "broad")
        assert result.decision is PrecheckDecision.SKIP

    def test_out_of_grade_matches_do_not_count(self, library):
        """Two matches total, but only one in grade → SKIP."""
        fake = [
            _match(library.entries[0], 0.85, grade_compatible=True),
            _match(library.entries[1], 0.85, grade_compatible=False),
        ]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(library, [0.1] * 4, "4", "broad")
        assert result.decision is PrecheckDecision.SKIP

    def test_low_confidence_matches_do_not_count(self, library):
        """Matches below LIST_MATCH_THRESHOLD don't qualify even when in grade."""
        fake = [
            _match(library.entries[0], LIST_MATCH_THRESHOLD - 0.01),
            _match(library.entries[1], LIST_MATCH_THRESHOLD - 0.01),
        ]
        with patch.object(library, "find_matches", return_value=fake):
            result = library_precheck(library, [0.1] * 4, "4", "broad")
        assert result.decision is PrecheckDecision.SKIP


# ---------------------------------------------------------------------------
# Response builders (Section 14.4, 14.6)
# ---------------------------------------------------------------------------


class TestResponseBuilders:
    def test_verbatim_with_matching_phrase_no_preface_rename(self, library):
        m = _match(library.entries[0], 0.95)
        result = build_verbatim_response(m, user_query_skill_phrase="Pizza table strategy")
        assert "Pizza table strategy" in result
        # No "(titled …)" rename when phrases match
        assert "(titled" not in result

    def test_verbatim_preserves_user_vocab_when_different(self, library):
        m = _match(library.entries[0], 0.95)
        result = build_verbatim_response(
            m,
            user_query_skill_phrase="topic sentence and supporting details",
        )
        # Both the user's phrasing AND the library's title should appear
        assert "topic sentence and supporting details" in result
        assert "Pizza table strategy" in result
        assert "(titled" in result

    def test_verbatim_includes_citation(self, library):
        m = _match(library.entries[0], 0.95)
        result = build_verbatim_response(m)
        # Fm5: soft conditional form + FULL title; never the "Teal book" shorthand.
        assert "If you have the 'Launching the Writers Workshop 3-12' book" in result
        assert "p.64" in result
        assert "Teal book" not in result

    def test_resolve_full_book_title_uses_assembler_single_source(self, library):
        """DRY lock: the resolved title must be the ASSEMBLER's canonical value,
        not a literal re-hardcoded in library_precheck. A future re-hardcode or
        a map reword the resolver misses would break this test."""
        from retrieval.assembler import _BOOK_FULL_TITLE
        from retrieval.library_precheck import _resolve_full_book_title
        # entries[0].book_reference contains "Teal book …" → maps to the assembler's canonical 3-12 title.
        assert _resolve_full_book_title(library.entries[0]) == _BOOK_FULL_TITLE["Teal"]

    def test_ask_user_message_cites_title_and_book(self, library):
        m = _match(library.entries[0], 0.87)
        msg = build_ask_user_message(m)
        assert "Pizza table strategy" in msg
        # "p. 64" is expanded to "page 64" so the response carries the explicit
        # 'page N' token required by the book-citation rule.
        assert "Teal book page 64" in msg
        assert "digital resources" in msg.lower()
        assert "verbatim" in msg.lower() or "generate" in msg.lower()

    def test_surface_list_shows_numbered_titles(self, library):
        matches = [
            _match(library.entries[0], 0.85),
            _match(library.entries[1], 0.80),
        ]
        msg = build_surface_list_message(matches)
        assert "1." in msg and "2." in msg
        assert "Pizza table strategy" in msg
        assert "Snapple details" in msg
        assert "Which one" in msg


# ---------------------------------------------------------------------------
# E7 — verbatim pull renders 4-step blocks + ends with the E2 close
# ---------------------------------------------------------------------------


class TestVerbatimE7BlocksAndClose:
    """Brady E7 (07:30): a named-lesson verbatim pull must (1) render the ML
    body in 4-step block shape (Fm2 — Step headers on their own blocks, never
    one glued paragraph), (2) keep the Fm5 soft citation, and (3) END with the
    E2 customization close, matching the generated SCRIPTED_ML path where the
    close is the final paragraph. The E2 string is the SINGLE source imported
    from handlers.scripted_ml — never duplicated in the verbatim builder."""

    def test_verbatim_ends_with_e2_customization_close(self, library):
        from handlers.scripted_ml import _E2_FOLLOWUP

        m = _match(library.entries[0], 0.95)
        result = build_verbatim_response(
            m, user_query_skill_phrase="Pizza table strategy"
        )
        # E2 close is the FINAL \n\n-separated paragraph, verbatim + single-source.
        assert result.split("\n\n")[-1] == _E2_FOLLOWUP
        assert result.rstrip().endswith(_E2_FOLLOWUP)

    def test_verbatim_body_renders_in_step_blocks(self, library):
        """The fixture complete_ml_text is 'Step 1 — Introduce the skill. ' * 30
        — a single glued run of Step-N headers. The SHARED Fm2 blockifier
        (_blockify_steps) must split them onto their own blocks, never deliver
        one giant paragraph."""
        m = _match(library.entries[0], 0.95)
        result = build_verbatim_response(m)
        # glued "…skill. Step 1 —" becomes a paragraph boundary
        assert "Introduce the skill.\n\nStep 1 —" in result
        # multiple \n\n block boundaries present (preface + step blocks + tail)
        assert result.count("\n\n") >= 3

    def test_verbatim_citation_precedes_e2_close(self, library):
        """Order: preface → 4-step body → soft citation → E2 close LAST (Fm5
        citation retained, E2 the final paragraph)."""
        from handlers.scripted_ml import _E2_FOLLOWUP

        m = _match(library.entries[0], 0.95)
        result = build_verbatim_response(m)
        citation = "If you have the 'Launching the Writers Workshop 3-12' book"
        assert citation in result  # Fm5 soft citation retained
        assert "Teal book" not in result  # no shorthand (Fm5)
        assert result.index(citation) < result.index(_E2_FOLLOWUP)
        assert result.split("\n\n")[-1] == _E2_FOLLOWUP
        # The page TEXT was never asserted, so a plural-rendering regression
        # ("…on pages 64.") shipped green. library_precheck.py:472 passes a
        # SCALAR page — lock the singular rendering at this consumer.
        assert (
            f"you'll find this lesson on p.{library.entries[0].page_number}." in result
        )

    def test_verbatim_close_present_even_without_citation(self, library):
        """The E2 close is UNCONDITIONAL; the Fm5 citation is conditional. When
        no book title / page resolves, the response still ends with the close."""
        import dataclasses

        from handlers.scripted_ml import _E2_FOLLOWUP

        entry = dataclasses.replace(
            library.entries[0],
            book_reference="",
            page_number=None,
            source_document="",
        )
        result = build_verbatim_response(_match(entry, 0.95))
        assert "If you have the" not in result  # no citation resolvable
        assert result.split("\n\n")[-1] == _E2_FOLLOWUP  # close still last


# ---------------------------------------------------------------------------
# P2 / recert B3 — the candidate pool must be filtered by grade BEFORE it is
# truncated, or grade-siblings eat every slot and the filter throws them away.
# ---------------------------------------------------------------------------


class TestGradeSiblingCrowding:
    """Brady's 24 MLs are grade-parallel: 'Determine the strongest side' has 12
    entries (K,1,2,3,4,5 x day1,day2), 'Recognize opinion topics' and 'Write an
    opinion' 6 each. library_precheck took the GLOBAL top-5 and only THEN
    filtered by grade, so the out-grade copies of the SAME lesson consumed every
    slot before the filter ran.

    Measured live against the shipped index with realistic named asks
    ("Give me the 'X' mini-lesson for grade N", campaign/recert/
    probe_sibling_crowding.py): out-grade siblings took 4 of 5 slots on almost
    every probe; separation was UNDEFINED on 12/18 (median in-grade pool = 1);
    and 'Determine the strongest side' at grade K came back with an EMPTY pool
    -> precheck SKIPs -> the LLM ad-libs the named lesson (April non-neg #7).

    Filtering first (find_best_in_grade over-fetches, then filters, then
    truncates) took undefined separation 12/18 -> 0/18 and the median pool
    1 -> 4 on the same probes.
    """

    def _sibling_library(self):
        """One lesson published per grade, K first — mirrors Brady's MLs.

        The K entry is authored LAST so a naive global top-5 (which keeps
        insertion order among equal scores) drops it: the 5 out-grade siblings
        fill the pool and the grade filter then discards all of them.
        """
        entries = [
            _entry(f"lib-persuasive-{g}-ml2-strongest-side",
                   "Determine the strongest side", grade_levels=[g])
            for g in ("1", "2", "3", "4", "5", "K")
        ]
        return MLLibrary(entries)

    def test_in_grade_entry_survives_a_field_of_out_grade_siblings(self):
        lib = self._sibling_library()
        # Every sibling shares one HyDE text, so a named ask scores them
        # identically — exactly the real case, where only the grade differs.
        emb = [1.0, 0.0, 0.0, 0.0]
        lib._hyde_embeddings = {e.ml_id: [[1.0, 0.0, 0.0, 0.0]] for e in lib.entries}

        # CURRENT SHAPE, reproduced: truncate to 5, then filter -> K is gone.
        top5 = lib.find_matches(emb, user_grade="K", top_k=5)
        assert len(top5) == 5
        assert [m for m in top5 if m.grade_compatible] == [], (
            "fixture drift: this test exists because the K entry is crowded out"
        )

        # FILTER-FIRST: the K entry must be found.
        pool = lib.find_best_in_grade(emb, user_grade="K", top_k=5)
        assert pool, "find_best_in_grade must not return an empty pool here"
        assert all(m.grade_compatible for m in pool)
        assert pool[0].entry.ml_id == "lib-persuasive-K-ml2-strongest-side"

    def test_precheck_pool_is_grade_filtered_before_truncation(self):
        """The precheck itself — not just the library helper — must survive it.

        This is the end-to-end lock: with 5 out-grade siblings ranked above it,
        a grade-K named ask must still reach a decision instead of SKIPping into
        LLM ad-lib.
        """
        lib = self._sibling_library()
        lib._hyde_embeddings = {e.ml_id: [[1.0, 0.0, 0.0, 0.0]] for e in lib.entries}

        result = library_precheck(
            library=lib,
            query_embedding=[1.0, 0.0, 0.0, 0.0],
            user_grade="K",
            query_specificity="specific",
            user_skill_phrase="determine the strongest side",
            user_writing_mode=None,
        )
        assert result.decision is not PrecheckDecision.SKIP, (
            "a named ask for a lesson that EXISTS at the teacher's grade must "
            "not SKIP into generation just because out-grade siblings outranked it"
        )
        assert result.best_match is not None
        assert result.best_match.entry.grade_levels == ["K"]
