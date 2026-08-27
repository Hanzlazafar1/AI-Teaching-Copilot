"""Tests for validation/citations.py (Wave 0 Part 2 test colocation)."""

from __future__ import annotations

import re

import unicodedata

import pytest

from validation.citations import (
    PAGE_TOKEN,
    _CITED_PAGE_RE,
    _PAGE_SCRUB_RE,
    _cited_pages,
    scrub_unverifiable_citations,
    validate_book_citation,
)


class TestUnverifiableCitationScrubber:
    """scrub_unverifiable_citations removes citations the response couldn't
    have earned from retrieval — invented pages, invented book names, orphan
    'digital resources' mentions. Policy principle: better to omit than to
    cite wrong. Teachers who look up a wrong page in their physical book
    lose trust in the whole system."""

    def test_verified_full_title_and_page_preserved(self):
        """Response uses the full book title + a page from retrieved
        headers — no scrub needed, passthrough."""
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "See Launching the Writers Workshop 3-12, page 64, for the table-top strategy."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "Launching the Writers Workshop 3-12" in out
        assert "page 64" in out
        assert removed == []

    def test_shorthand_teal_stripped_unconditionally(self):
        """'Teal book' is internal shorthand. Teacher-facing responses
        must use the full title. Scrubber strips 'Teal book' regardless
        of what's in retrieval — the prompt tells the generator to use
        the full title, the scrubber enforces it as a safety net."""
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "See the Teal book, page 64, for the table-top strategy."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "teal" not in out.lower()
        assert any("teal" in r.lower() for r in removed)

    def test_shorthand_k2_stripped_unconditionally(self):
        ctx = "[1] Source: k2-s3-ml02 | Book: Launching the Writers Workshop K-2 | Page: 14"
        resp = "See the K-2 book, page 14, for the lesson."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "k-2 book" not in out.lower()
        assert any("k-2" in r.lower() for r in removed)

    def test_invented_page_stripped(self):
        """Invented page (not in retrieved headers) is removed from the
        response, and the removal is recorded for logging."""
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "See Launching the Writers Workshop 3-12, page 113, for the strategy."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "page 113" not in out
        assert any("page 113" in r.lower() for r in removed)

    def test_invented_full_title_stripped_when_only_k2_retrieved(self):
        ctx = "[1] Source: k2-s3-ml02 | Book: Launching the Writers Workshop K-2 | Page: 14"
        resp = "See Launching the Writers Workshop 3-12 for this lesson."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "3-12" not in out
        assert any("3-12" in r for r in removed)

    def test_invented_full_title_stripped_when_only_teal_retrieved(self):
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "See Launching the Writers Workshop K-2, page 64, for this lesson."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "k-2" not in out.lower()
        assert any("k-2" in r.lower() for r in removed)

    def test_k2_grade_band_mention_preserved(self):
        """Ambiguous case: 'K-2 kindergarteners' is a grade-band descriptor,
        not a book attribution. Scrubber should NOT strip it."""
        ctx = "[1] Source: lww312-s8-ml05 | Page: 64"
        resp = "For K-2 kindergarteners the approach differs."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "K-2 kindergarteners" in out

    def test_digital_resources_stripped_when_no_launch_chunk(self):
        ctx = "[1] Source: ep11-meet-to-teach | Type: episode_explanation"
        resp = (
            "Here are five tips for your workshop. "
            "You can also find the graphic organizer in the book's digital resources. "
            "Any questions?"
        )
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "digital resources" not in out.lower()
        # The rest of the response is preserved
        assert "five tips" in out
        assert "Any questions?" in out

    def test_digital_resources_preserved_when_launch_chunk_present(self):
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "See Launching the Writers Workshop 3-12, page 64. The graphic organizer is in the book's digital resources."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "digital resources" in out
        assert removed == []

    def test_empty_response_no_ops(self):
        out, removed = scrub_unverifiable_citations("", "[1] Source: lww312-s8-ml05 | Page: 64")
        assert out == ""
        assert removed == []

    def test_empty_context_scrubs_all_citations(self):
        """If there's no retrieved context at all, no citation is verifiable.
        Everything gets stripped."""
        out, removed = scrub_unverifiable_citations(
            "See the Teal book, page 42, for details. The graphic organizer is in the digital resources.",
            "",
        )
        assert "page 42" not in out
        assert "teal" not in out.lower()
        assert "digital resources" not in out.lower()

    def test_p_dot_notation_scrubbed(self):
        ctx = "[1] Source: lww312-s8-ml05 | Page: 64"
        resp = "Look at p. 99 in the book for the strategy."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "p. 99" not in out
        assert any("99" in r for r in removed)

    # -- Paragraph preservation on REMOVAL (Task 8 review round 2, Brady #11) --
    #
    # These make a real removal fire adjacent to a "\n\n" paragraph break
    # between two REAL paragraphs. The match/removal regexes formerly padded
    # their boundaries with raw \s* / \s+; since \s matches "\n", a citation
    # sitting at a paragraph end had its trailing "\n\n" swallowed, flattening
    # the two paragraphs into one. The removal must strip the citation while
    # leaving the paragraph break AND the neighbouring paragraph intact.

    def test_invented_page_adjacent_to_break_preserves_paragraph(self):
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 12"
        resp = "Model the strategy on page 99\n\nThen send students off to draft."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert any("99" in r for r in removed)      # removal actually fired
        assert "99" not in out                       # invented page gone
        assert "\n\n" in out                         # paragraph break survived
        assert "Then send students off to draft." in out  # neighbour intact

    def test_book_shorthand_adjacent_to_break_preserves_paragraph(self):
        resp = "Check the Teal book\n\nNext, model it for your students."
        out, removed = scrub_unverifiable_citations(resp, "")
        assert any("teal" in r.lower() for r in removed)
        assert "teal" not in out.lower()
        assert "\n\n" in out
        assert "Next, model it for your students." in out

    def test_full_title_adjacent_to_break_preserves_paragraph(self):
        # No Teal chunk retrieved -> the full 3-12 title is unverifiable and
        # gets stripped; it sits at a paragraph end.
        ctx = "[1] Source: k2-s3-ml02 | Book: Launching the Writers Workshop K-2 | Page: 14"
        resp = "See Launching the Writers Workshop 3-12\n\nThen begin the lesson."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert any("3-12" in r for r in removed)
        assert "3-12" not in out
        assert "\n\n" in out
        assert "Then begin the lesson." in out

    def test_digital_resources_sentence_between_paragraphs_preserves_both(self):
        # The removed sentence is its own middle paragraph; BOTH breaks and
        # BOTH neighbouring paragraphs must survive.
        resp = (
            "First, teach the strategy.\n\n"
            "Remember to check the digital resources for the organizer.\n\n"
            "Finally, send them off to write."
        )
        out, removed = scrub_unverifiable_citations(resp, "")
        assert removed  # a removal fired
        assert "digital resources" not in out.lower()
        assert out.count("\n\n") == 2  # both paragraph breaks survived
        assert "First, teach the strategy." in out
        assert "Finally, send them off to write." in out

    # -- Word-boundary guard on page_pattern (audit pass-2) -------------------
    #
    # page_pattern's citation alternation (?:page|pp\.?|pg\.?|p\.) had NO
    # leading \b, so any ordinary word ending in "p"/"pp"/"pg" right before a
    # number was misread as a "p."/"pp."/"pg." page token and torn out
    # mid-word. scrub_unverifiable_citations runs on EVERY delivered response,
    # so this shipped to teachers. Live repro:
    #   "Have them stop. 2 sentences..." -> "Have them sto sentences..."
    #   "Keep the app. 5 minutes..."     -> "Keep the a minutes..."
    # (a) proves no mid-word corruption; (b)/(c) prove real invented/verified
    # page scrubbing is untouched by the fix.

    def test_word_ending_in_p_before_number_not_corrupted(self):
        """A normal word ending in p/pp/pg immediately before a number is NOT
        a page citation and must survive the scrubber byte-for-byte."""
        for text in (
            "Have them stop. 2 sentences later, model the strategy.",
            "Keep the app. 5 minutes is plenty for the mini-lesson.",
            "Ask them to keep. 3 examples ready for sharing.",
        ):
            out, removed = scrub_unverifiable_citations(text, retrieved_context="")
            assert out == text, f"mid-word corruption: {text!r} -> {out!r}"
            assert removed == [], f"unexpected removal for {text!r}: {removed!r}"

    def test_preposition_before_page_is_not_matched_mid_word(self):
        """THE OTHER HALF of the mid-word class — never guarded, never tested.

        _PAGE_SCRUB_RE strips an optional leading preposition so removing a
        citation leaves no dangling "on"/"at"/"see". That alternation had NO
        left guard, so it matched INSIDE a word: "wh|at page 2" and
        "less|on page 2". The scrubber then ate the word's tail with the
        citation.

        This SHIPPED to a teacher — drive-cache session 496f0423, inside a
        read-aloud mini-lesson script:
            '...watched the little flames wiggle." Then I wonder wh should be.'

        The sibling test above (test_word_ending_in_p_before_number_not_corrupted)
        guards only the _PAGE_WORD half, and PROGRESS.md records the class as
        hardened ("mid-word safety improved \\b -> (?<![^\\W_])") on the strength
        of it. Half the class was fixed; a green test certified the whole.
        """
        for text in (
            "Then I wonder what page 2 should be.",       # 'at' inside "what"
            "Model this lesson page 2 for students.",     # 'on' inside "lesson"
            "Give me a reason page 3 works better.",      # 'on' inside "reason"
            "Which season page 4 covers is unclear.",     # 'on' inside "season"
        ):
            out, _ = scrub_unverifiable_citations(text, retrieved_context="")
            # The page may go (it is unverifiable) — the WORD may never be torn.
            for word in ("what", "lesson", "reason", "season"):
                if word in text:
                    assert word in out, (
                        f"mid-word corruption: {text!r} -> {out!r} (lost {word!r})"
                    )

    def test_dangling_preposition_still_removed_when_it_is_a_real_word(self):
        """The guard must not cost the feature: a REAL leading preposition is
        still consumed with the citation, so no dangling 'on'/'see' is left."""
        for text, must_not_end_with in (
            ("You'll find this lesson on page 113.", "on"),
            ("Details are at page 99.", "at"),
            ("For more, see page 77.", "see"),
        ):
            out, removed = scrub_unverifiable_citations(text, retrieved_context="")
            assert removed, f"the invented page must still be removed from {text!r}"
            # NB: a plain endswith() is wrong here — "lesson".endswith("on") is
            # True, i.e. the same substring bug this whole test class is about.
            # The dangling word must be checked as a WORD.
            assert not re.search(rf"\b{must_not_end_with}\b\s*\.?\s*$", out), (
                f"dangling preposition left behind: {out!r}"
            )

    def test_invented_page_still_scrubbed_after_boundary_fix(self):
        """Regression guard: a real invented 'page 113' (no retrieved context
        to verify against) is still stripped after the \\b fix."""
        out, removed = scrub_unverifiable_citations(
            "Model the table-top strategy on page 113 for your class.",
            retrieved_context="",
        )
        assert "page 113" not in out
        assert any("113" in r for r in removed)

    def test_verified_page_still_kept_after_boundary_fix(self):
        """Regression guard: a real 'page 64' that IS in the retrieved chunk
        headers is still kept after the \\b fix."""
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "See Launching the Writers Workshop 3-12, page 64, for the strategy."
        out, removed = scrub_unverifiable_citations(resp, ctx)
        assert "page 64" in out
        assert removed == []


class TestBookCitation:
    """Citation policy is conservative: validator NEVER demands citations.

    It only flags hallucinated ones (pages/books that don't match what
    was actually retrieved) so the scrubber can strip them. The principle
    is 'better to omit than to cite wrong' — teachers looking up a wrong
    cited page in their book lose trust in the whole system; a missing
    page is recoverable via a follow-up 'what page?'.
    """

    # --- No-demand cases (citations are optional now) ------------------------

    def test_no_launch_chunk_no_check(self):
        ctx = "[1] Source: ep3-elem-skill1-intro | Type: episode_explanation"
        assert validate_book_citation("Any response.", ctx) == []

    def test_launch_chunk_without_citation_passes(self):
        """Brady R2-citation policy: a Launch chunk was retrieved but the
        response is a conversational ack / short reply. NO citation required."""
        ctx = "[1] Source: lww312-s8-ml05-table-top | Page: 64"
        resp = "Doing well, thanks! What would you like to teach next?"
        assert validate_book_citation(resp, ctx) == []

    def test_missing_page_no_longer_flagged(self):
        """Missing page citation is fine — we no longer demand one."""
        ctx = "[1] Source: lww312-s8-ml05-table-top | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "Use the table-top strategy. It's a useful approach for organizing paragraphs."
        assert validate_book_citation(resp, ctx) == []

    def test_missing_digital_resources_no_longer_flagged(self):
        """Missing 'digital resources' reminder is fine — optional."""
        ctx = "[1] Source: lww312-s8-ml05-table-top | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "See Launching the Writers Workshop 3-12, page 64."
        assert validate_book_citation(resp, ctx) == []

    def test_missing_book_name_no_longer_flagged(self):
        """Response can cite a page without naming the book."""
        ctx = "[1] Source: lww312-s8-ml05-table-top | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "See page 64 for more. The graphic organizer is in the digital resources."
        assert validate_book_citation(resp, ctx) == []

    # --- Shorthand detection (NEW) -------------------------------------------

    def test_shorthand_teal_book_flagged(self):
        """Shorthand 'Teal book' is internal Smekens jargon — responses for
        teachers must use the full title. Flag unconditionally so the
        scrubber can strip it."""
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "Use the Teal book, page 64, for the strategy."
        errors = validate_book_citation(resp, ctx)
        assert any("shorthand" in e.lower() and "teal" in e.lower() for e in errors)

    def test_shorthand_k2_book_flagged(self):
        ctx = "[1] Source: k2-s3-ml02 | Book: Launching the Writers Workshop K-2 | Page: 14"
        resp = "Use the K-2 book, page 14, for the strategy."
        errors = validate_book_citation(resp, ctx)
        assert any("shorthand" in e.lower() and "k-2" in e.lower() for e in errors)

    # --- Page-hallucination (kept as hard check) -----------------------------

    def test_cited_page_matches_retrieved_passes(self):
        ctx = "[1] Source: lww312-s8-ml05-table-top | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = (
            "See Launching the Writers Workshop 3-12, page 64, for the table-top strategy. "
            "The graphic organizer is in the book's digital resources."
        )
        assert validate_book_citation(resp, ctx) == []

    def test_cited_page_not_in_retrieved_is_flagged(self):
        """Response invents a page that wasn't in any retrieved chunk —
        teacher would look this up in their book and not find it."""
        ctx = "[1] Source: lww312-s8-ml05-table-top | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = (
            "See Launching the Writers Workshop 3-12, page 7, for the table-top strategy. "
            "The graphic organizer is in the book's digital resources."
        )
        errors = validate_book_citation(resp, ctx)
        assert any("don't match" in e.lower() and "page(s) 7" in e.lower() for e in errors)
        assert any("page(s) 64" in e for e in errors)  # valid pages surfaced

    def test_multiple_retrieved_pages_response_picks_one(self):
        ctx = (
            "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64\n"
            "[2] Source: lww312-s9-ml02 | Book: Launching the Writers Workshop 3-12 | Page: 78"
        )
        resp = (
            "See Launching the Writers Workshop 3-12, page 78. The graphic organizer is in the "
            "book's digital resources."
        )
        assert validate_book_citation(resp, ctx) == []

    def test_multiple_retrieved_pages_response_invents_different(self):
        ctx = (
            "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64\n"
            "[2] Source: lww312-s9-ml02 | Book: Launching the Writers Workshop 3-12 | Page: 78"
        )
        resp = (
            "See Launching the Writers Workshop 3-12, page 99. The graphic organizer is in "
            "the book's digital resources."
        )
        errors = validate_book_citation(resp, ctx)
        assert any("page(s) 99" in e.lower() and ("64" in e and "78" in e) for e in errors)

    def test_response_uses_p_dot_notation(self):
        ctx = "[1] Source: lww312-s8-ml05-table-top | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = (
            "See Launching the Writers Workshop 3-12, p. 64, for the table-top strategy. "
            "The graphic organizer is in the book's digital resources."
        )
        assert validate_book_citation(resp, ctx) == []

    def test_retrieved_has_no_page_metadata_skips_hallucination_check(self):
        """Legacy chunks without page_number: no retrieved_pages to compare
        against, so we don't flag any cited page."""
        ctx = "[1] Source: lww312-s8-ml05-table-top | Book: Launching the Writers Workshop 3-12"
        resp = "See Launching the Writers Workshop 3-12, page 42. The graphic organizer is in the digital resources."
        # No "Page: N" in the context → no hallucination check.
        assert validate_book_citation(resp, ctx) == []

    # --- Invented-book-name checks (NEW) -------------------------------------

    def test_invented_k2_full_title_flagged_when_only_teal_retrieved(self):
        """Only Teal chunks retrieved; response cites the K-2 book full
        title as if it were a source. Misleads teachers to look in the
        wrong physical book."""
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        resp = "Use Launching the Writers Workshop K-2, page 64. The graphic organizer is in the digital resources."
        errors = validate_book_citation(resp, ctx)
        assert any("k-2" in e.lower() and "no k-2" in e.lower() for e in errors)

    def test_invented_teal_full_title_flagged_when_only_k2_retrieved(self):
        ctx = "[1] Source: k2-s3-ml02 | Book: Launching the Writers Workshop K-2 | Page: 14"
        resp = "Use Launching the Writers Workshop 3-12, page 14. The graphic organizer is in the digital resources."
        errors = validate_book_citation(resp, ctx)
        assert any("3-12" in e.lower() and "no launching 3-12" in e.lower() for e in errors)

    # --- No-launch-in-context hallucination checks (NEW) ---------------------

    def test_response_cites_page_with_no_launch_chunk_flagged(self):
        """No Launch chunk retrieved at all. Response shouldn't cite any
        book page — there's nothing to tie the citation to."""
        ctx = "[1] Source: ep11-meet-to-teach | Type: episode_explanation"
        resp = "See Launching the Writers Workshop 3-12, page 42, for the strategy."
        errors = validate_book_citation(resp, ctx)
        assert any("no launch" in e.lower() or "no source" in e.lower() for e in errors)

    def test_digital_resources_without_launch_chunk_flagged(self):
        ctx = "[1] Source: ep11-meet-to-teach | Type: episode_explanation"
        resp = "You can also find it in the book's digital resources."
        errors = validate_book_citation(resp, ctx)
        assert any("digital resources" in e.lower() for e in errors)


# =========================================================================
# The page-token GRAMMAR — locked as a CLASS, not per-separator
# =========================================================================
#
# THE BUG THESE LOCK (all three parts of one class defect):
#
#   1. The scrubber's gap between the page word and the page number was
#      `[^\S\n]*` — HORIZONTAL WHITESPACE ONLY. It never matches a hyphen, so
#      "page-66" sailed through while "page 66" was stripped: one response
#      could WITHHOLD and REVEAL the same page simultaneously. Brady's rule is
#      "book + page ONLY at 100% confidence, otherwise stay silent" — a
#      separator we forgot to enumerate must never be the thing that decides
#      whether a teacher is shown an unverifiable page.
#
#   2. `_CITED_PAGE_RE` (the VALIDATOR's extractor) had the SAME flaw via
#      `\s*`, so `_cited_pages("the page-66 lesson")` returned `set()`. The
#      validator was blind to exactly the input the scrubber missed — no
#      second line of defence. THE DIVERGENCE IS THE CLASS BUG: two regexes
#      that both claim to know "what a page citation is" and disagree.
#
#   3. Removal was emphasis-unaware: `**page 66**` -> `** **`, a blank
#      emphasis slot shipped to a teacher.
#
# The fix is a single shared grammar (`PAGE_TOKEN`) with a NEGATIVELY-defined
# separator class, so these tests are written to fail for ANY future
# separator/emphasis miss — not just the ones we happened to observe.


def _unicode_dashes() -> list[str]:
    """EVERY dash-punctuation codepoint (Unicode category Pd) in the BMP,
    GENERATED from the Unicode database at test time.

    Deliberately generated rather than typed out: a hand-written list would
    only ever contain the separators we already know about, which is precisely
    the whack-a-mole that produced this defect. If Python's Unicode tables gain
    a new dash, this test set gains it too — and the implementation must
    already handle it, because it defines the separator by what it is NOT.
    """
    return [chr(cp) for cp in range(0x10000) if unicodedata.category(chr(cp)) == "Pd"]


# Separator forms that must ALL be treated identically. Union of:
#   * horizontal whitespace, incl. the invisible ones (NBSP, thin/narrow/figure
#     space) that look exactly like a plain space to a teacher;
#   * every Unicode dash (generated);
#   * non-dash binders that are neither whitespace nor a dash — U+2212 MINUS
#     SIGN (a classic hyphen look-alike), the "Page: N" label form that a
#     leaked chunk header produces, and numero/hash marks;
#   * multi-character and padded gaps ("page -- 66", "page - 66");
#   * the EMPTY gap ("page66", and the "p.66" form build_soft_citation emits).
_SEPARATORS: list[str] = (
    [" ", "  ", "\t", "\xa0", " ", " ", " "]
    + _unicode_dashes()
    + ["−", ":", ": ", "#", "№"]
    + ["--", " - ", " – ", "\xa0-\xa0", "\t-\t"]
    + [""]
)


def _sep_id(sep: str) -> str:
    """Readable pytest id (raw codepoints keep the ids unambiguous)."""
    return "EMPTY" if sep == "" else "+".join(f"U{ord(c):04X}" for c in sep)


_SEP_PARAMS = [pytest.param(s, id=_sep_id(s)) for s in _SEPARATORS]


class TestPageTokenGrammarIsShared:
    """The scrubber and the validator must be the SAME grammar, by construction.

    A behavioural test alone can't prove non-divergence — someone could
    hand-edit one regex and only break the cases we thought to write. These
    assert the two consumers literally compile from the one `PAGE_TOKEN`
    string, so a future edit that re-forks them fails here immediately.
    """

    def test_validator_extractor_compiles_from_the_shared_grammar(self):
        assert PAGE_TOKEN in _CITED_PAGE_RE.pattern

    def test_scrubber_compiles_from_the_shared_grammar(self):
        assert PAGE_TOKEN in _PAGE_SCRUB_RE.pattern

    def test_shared_grammar_is_not_trivially_empty(self):
        """Guard the two asserts above against vacuity via `"" in pattern`."""
        assert len(PAGE_TOKEN) > 20


@pytest.mark.parametrize("sep", _SEP_PARAMS)
class TestPageSeparatorClass:
    """Separator-SHAPE independence.

    FUTURE BUG CAUGHT: any newly-encountered separator (en-dash, em-dash,
    U+2212, NBSP, a fullwidth hyphen, "page: 66" from a leaked chunk header)
    silently bypassing the scrubber or the validator — i.e. exactly the
    "page-66" defect, reintroduced by a different codepoint.
    """

    def test_validator_sees_the_page_whatever_the_separator(self, sep):
        assert _cited_pages(f"the page{sep}66 lesson") == {66}

    def test_scrubber_removes_the_unverified_page_whatever_the_separator(self, sep):
        out, removed = scrub_unverifiable_citations(f"See page{sep}66 for this.", "")
        assert removed, "no removal fired"
        assert "66" not in out, f"unverifiable page survived: {out!r}"

    def test_scrubber_keeps_the_verified_page_whatever_the_separator(self, sep):
        """The mirror image: a page that IS in the retrieved headers must
        survive every separator form, byte-identical. Without this, a
        'scrub everything' over-correction would pass the test above."""
        ctx = "[1] Source: lww312-s8-ml05 | Page: 64"
        text = f"See page{sep}64 for this."
        out, removed = scrub_unverifiable_citations(text, ctx)
        assert out == text
        assert removed == []

    def test_scrubber_and_validator_never_disagree(self, sep):
        """THE class-bug lock. Whatever the separator, the two layers must
        reach the SAME verdict about whether a page citation is present. When
        they diverge, the second line of defence silently disappears."""
        text = f"Model the strategy on page{sep}66 for your class."
        _, removed = scrub_unverifiable_citations(text, retrieved_context="")
        assert (66 in _cited_pages(text)) == bool(removed)


class TestPageRangeGrammar:
    """A range cites TWO pages; both must clear the same bar.

    FUTURE BUG CAUGHT: "pages 64-65" where only 64 was retrieved — the
    unverifiable 65 riding along on a verified neighbour.
    """

    def test_validator_extracts_both_ends_of_a_range(self):
        assert _cited_pages("See pages 64-65 for this.") == {64, 65}

    def test_range_with_an_unverified_end_is_scrubbed(self):
        ctx = "[1] Source: lww312-s8-ml05 | Page: 64"
        out, removed = scrub_unverifiable_citations("See pages 64-65 for this.", ctx)
        assert removed
        assert "65" not in out

    def test_range_fully_verified_survives(self):
        ctx = "[1] Source: lww312-s8-ml05 | Page: 64\n[2] Source: lww312-s8-ml06 | Page: 65"
        text = "See pages 64-65 for this."
        out, removed = scrub_unverifiable_citations(text, ctx)
        assert out == text
        assert removed == []

    def test_plural_page_word_is_not_a_blind_spot(self):
        """'pages 64' bypassed the old grammar entirely (the alternation had
        only the singular 'page', which then needed a digit where the 's' was)."""
        out, removed = scrub_unverifiable_citations("See pages 99 for this.", "")
        assert removed
        assert "99" not in out


class TestEmphasisAwareRemoval:
    """Removal must not leave a hole in the markdown it cut the citation out of.

    FUTURE BUG CAUGHT: any emphasis/inline-code marker pair left orphaned
    around a removed citation — `** **`, `* *`, `_ _`, `` ` ` `` — shipped to
    a teacher as a visible blank slot (the same failure that got the first Fm5
    attempt reverted).
    """

    WRAPS = ("**", "*", "***", "`", "_", "___")

    @pytest.mark.parametrize("wrap", WRAPS)
    def test_emphasised_unverified_page_leaves_no_blank_slot(self, wrap):
        text = f"See {wrap}page 66{wrap} for the anchor chart."
        out, removed = scrub_unverifiable_citations(text, "")
        assert removed
        assert "66" not in out
        assert wrap[0] not in out, f"orphan emphasis marker left: {out!r}"

    @pytest.mark.parametrize("wrap", WRAPS)
    def test_emphasised_verified_page_survives_byte_identical(self, wrap):
        """The emphasis handling must not become a licence to rewrite text we
        had no reason to touch."""
        ctx = "[1] Source: lww312-s8-ml05 | Page: 64"
        text = f"See {wrap}page 64{wrap} for the anchor chart."
        out, removed = scrub_unverifiable_citations(text, ctx)
        assert out == text
        assert removed == []

    def test_emphasis_spanning_more_than_the_citation_is_not_torn(self):
        """The opposite over-reach: when the emphasis wraps a whole sentence,
        the markers belong to the SENTENCE, not the citation. Consuming them
        would break the teacher's bold run."""
        out, removed = scrub_unverifiable_citations(
            "**Model this on page 66 and then release them to write.**", ""
        )
        assert removed
        assert "66" not in out
        assert out.startswith("**") and out.rstrip().endswith("**")
        assert "Model this" in out and "release them to write" in out

    def test_emphasised_preposition_and_citation_removed_together(self):
        out, removed = scrub_unverifiable_citations(
            "Model it **on page 66** before releasing them.", ""
        )
        assert removed
        assert "66" not in out
        assert "*" not in out


class TestSeparatorClassDoesNotResurrectMidWordTearing:
    """The negative half of the separator widening.

    A negatively-defined separator admits MORE characters, so it could
    plausibly re-open the pass-2 mid-word bug (an ordinary word ending in
    p/pp/pg before a number read as a page token and torn out). These pin that
    it does not — and extend it to the newly-admitted joiners.

    FUTURE BUG CAUGHT: a separator widening that starts eating ordinary prose.
    """

    @pytest.mark.parametrize(
        "text",
        [
            # Sentence boundary: the number opens a NEW clause, it is not a page.
            "Have them stop. 2 sentences later, model the strategy.",
            "Keep the app. 5 minutes is plenty for the mini-lesson.",
            "Ask them to keep. 3 examples ready for sharing.",
            # Hyphen joiner must not turn ordinary hyphenated prose into a citation.
            "Use a top-3 list to rank their ideas.",
            "Give each group-2 a turn to share their draft.",
            "Set up. 4 stations around the room.",
            # Colon joiner must not eat a label that merely ends in p/pg.
            "Warm-up: 5 minutes of free writing.",
            "Wrap: 2 minutes to share out.",
            # A full stop is a TERMINATOR, never a citation separator.
            "Turn to the next page. 2 students will share their leads.",
        ],
    )
    def test_ordinary_prose_survives_byte_for_byte(self, text):
        out, removed = scrub_unverifiable_citations(text, retrieved_context="")
        assert out == text, f"mid-word/prose corruption: {text!r} -> {out!r}"
        assert removed == [], f"unexpected removal for {text!r}: {removed!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "Turn to the next page. 2 students will share their leads.",
            "Use a top-3 list to rank their ideas.",
        ],
    )
    def test_validator_agrees_ordinary_prose_cites_nothing(self, text):
        """Same grammar => the validator must also see no citation here. If it
        saw one it would flag a phantom and drive a pointless repair retry."""
        assert _cited_pages(text) == set()

    def test_newline_is_never_a_citation_separator(self):
        """`\\S`-based horizontal whitespace and the joiner class both exclude
        "\\n" — a page word at a line end and a number at the next line start
        are two different things, and joining them would let a removal swallow
        a paragraph break (Brady non-negotiable #11)."""
        text = "Turn to the next page\n\n66 students are ready."
        out, removed = scrub_unverifiable_citations(text, retrieved_context="")
        assert out == text
        assert removed == []
        assert _cited_pages(text) == set()


class TestValidatorSeesWhatTheScrubberMisses:
    """Defect part 2, stated as the invariant it broke: the validator is the
    SECOND line of defence. If the scrubber ever fails to strip an
    unverifiable page, `validate_book_citation` must still flag it so the
    repair loop can. A separator the validator cannot parse is a validator
    that cannot defend.
    """

    @pytest.mark.parametrize("sep", ["-", "–", "—", "\xa0", " ", ":", ""])
    def test_invented_page_is_flagged_whatever_the_separator(self, sep):
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        errors = validate_book_citation(f"Model the strategy on page{sep}99.", ctx)
        assert any("99" in e for e in errors), f"invented page{sep}99 not flagged"

    @pytest.mark.parametrize("sep", ["-", "–", "—", "\xa0", " ", ":", ""])
    def test_verified_page_is_not_flagged_whatever_the_separator(self, sep):
        ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 64"
        assert validate_book_citation(f"Model the strategy on page{sep}64.", ctx) == []
