"""Book/page citation enforcement + deterministic citation scrub.

Split out of validation/policy.py (Wave 0 Part 2). Verifies any citation the
response CHOSE to include is grounded in the retrieved Launch-book context
(never demands one), and strips unverifiable pages/book-names. Pure string-in /
string-out — no MiniLesson dep. Re-exported from validation.policy.
"""
from __future__ import annotations

import re


_LAUNCH_CHUNK_MARKERS = ("source: lww312", "source: k2-", "launching the writer")


def _launch_chunk_in_context(retrieved_context: str) -> bool:
    if not retrieved_context:
        return False
    ctx = retrieved_context.lower()
    return any(m in ctx for m in _LAUNCH_CHUNK_MARKERS)


# ===========================================================================
# THE PAGE-TOKEN GRAMMAR — ONE definition, shared by the scrubber AND the
# validator.
# ===========================================================================
#
# WHY THIS EXISTS. There used to be two independent answers to "what is a page
# citation?": the text-REMOVING pattern inside scrub_unverifiable_citations
# (gap = `[^\S\n]*`) and the page-EXTRACTING `_CITED_PAGE_RE` (gap = `\s*`).
# Both enumerated the separators someone had thought of, and both missed the
# same one — a hyphen. So "page-66" bypassed removal while "page 66" was
# stripped (ONE response could withhold and reveal the SAME page at once), and
# `_cited_pages("the page-66 lesson")` returned `set()`, so the validator could
# not flag what the scrubber had missed: no second line of defence.
#
# Two regexes that both claim to define a citation WILL drift apart — that
# divergence IS the bug, not a symptom of it. So there is now exactly one
# grammar (`PAGE_TOKEN`) and both layers compile from it. Adding a separator to
# one and not the other is no longer expressible.
#
# Brady's rule is "book title + page ONLY at 100% confidence, otherwise stay
# silent". A separator nobody remembered to list must never be the thing that
# decides whether a teacher is shown a page we cannot verify.

# Horizontal whitespace: space / tab / NBSP / thin space / … but NEVER a
# newline. `\S` is Unicode-aware, so `[^\S\n]` already admits every Unicode
# space separator (U+00A0, U+2009, U+202F, …) with no enumeration. Newline is
# excluded because a REMOVAL padded with `\s` would swallow the adjacent
# "\n\n" paragraph break (Brady non-negotiable #11), and because a page word
# at a line end and a number at the next line start are two different things.
_H = r"[^\S\n]"

# A "joiner": the optional glue between the page word and the page number.
#
# Defined NEGATIVELY, on purpose. Enumerating separators positively is
# whack-a-mole — hyphen, then en-dash, then U+2212 MINUS SIGN, then a
# fullwidth hyphen. Instead: a joiner is ANY character that is not
# alphanumeric, not whitespace, and not one of the carve-outs below. Every
# dash-like codepoint, every binder-like symbol (:, #, №) is therefore
# admitted BY CONSTRUCTION, including ones that do not exist yet.
#
# The carve-outs are principled — each would cause a FALSE positive, and none
# is here because we watched it fail:
#
#   . , ; ! ? …    TERMINATORS. A number after one opens a NEW clause ("Turn
#                  to the next page. 2 students share."); binding it to the
#                  page word would tear an ordinary sentence apart. Costs no
#                  real citation: the abbreviation forms carry their own
#                  period INSIDE the token (`p\.`, `pp\.?`, `pg\.?`).
#   ()[]{}<>"'     DELIMITERS. Consuming one half orphans the other — "page
#                  (66" would leave a stray ")".
#   * ` ~ / \ |    MARKDOWN / inline delimiters. Same orphan problem; emphasis
#                  is handled explicitly and symmetrically in _PAGE_SCRUB_RE.
_JOINER = r"[^\w\s.,;!?…()\[\]{}<>\"'*`~/\\|]"

# Word→number gap: joiner OPTIONAL ("page 66" has none, "page-66" has one).
# Bounded at 2 so "page--66" works without admitting an unbounded run.
_GAP = rf"{_H}*(?:{_JOINER}{{1,2}}{_H}*)?"
# Number→number gap of a RANGE ("64-65"): same class, but the joiner is
# REQUIRED — otherwise "page 64 66" would read as a range.
_RANGE_GAP = rf"{_H}*{_JOINER}{{1,2}}{_H}*"

# "Not preceded / followed by a letter or digit". `[^\W_]` is Unicode-aware
# word-char-minus-underscore, i.e. exactly "letter or digit".
#
# This replaces the plain `\b` added in audit pass-2 and keeps that fix intact:
# an ordinary word ending in p/pp/pg before a number ("stop. 2", "app. 5") is
# still NOT a page token, so the scrubber cannot tear words mid-token — it runs
# on EVERY delivered response, so that failure shipped to teachers. It is also
# strictly BETTER than `\b`, which treats "_" as a word character and so could
# never see the page inside markdown emphasis (`_page 66_`).
_LEFT_GUARD = r"(?<![^\W_])"
_RIGHT_GUARD = r"(?![^\W_])"

_PAGE_WORD = rf"{_LEFT_GUARD}(?:pages?|pp\.?|pg\.?|p\.)"

#: THE page-citation token — the single source of truth. Matches "page 64",
#: "page-64", "page—64", "page: 64", "page\xa064", "page66", "p.64", "pg. 64",
#: "pp. 64", "pages 64-65". Both `_CITED_PAGE_RE` (extraction, for the
#: validator) and `_PAGE_SCRUB_RE` (removal, for the scrubber) compile from
#: this string and nothing else, so they cannot disagree about what a citation
#: is. Exposes named groups `pg_n1` (page / range start) and `pg_n2` (range
#: end, optional) — a range cites TWO pages and BOTH must clear the bar.
PAGE_TOKEN = (
    rf"{_PAGE_WORD}{_GAP}(?P<pg_n1>\d+)"
    rf"(?:{_RANGE_GAP}(?P<pg_n2>\d+))?{_RIGHT_GUARD}"
)

# ---------------------------------------------------------------------------
# DETECTION / EXTRACTION regexes (module-level).
#
# The book-title patterns below deliberately keep \s (which matches "\n").
# They are used ONLY by validate_book_citation (.search → returns error
# strings) and by the _retrieved_pages helper (.findall → extracts page
# numbers for set comparison). NONE of them feed re.sub, so none modify or
# remove delivered text — they cannot swallow a "\n\n" paragraph break. For a
# detector, matching across a newline is strictly MORE robust (a book title
# wrapped across a line still gets flagged), so \s is correct there. The
# newline-safe [^\S\n] discipline applies to the text-REMOVING patterns.
# ---------------------------------------------------------------------------
# Extracts numeric page values from response text. Compiled from the shared
# PAGE_TOKEN grammar: whatever page form the scrubber can strip, the validator
# can see — and vice versa.
_CITED_PAGE_RE = re.compile(PAGE_TOKEN, re.IGNORECASE)
# Unused internally; retained for API stability. Aliased to the shared
# extractor rather than re-declared, so it cannot become a third, divergent
# answer to "what is a page citation?".
_PAGE_REF_RE = _CITED_PAGE_RE
# Pulls "Page: N" from chunk headers in retrieved_context. Only chunk
# headers set this token (via assembler._format_chunk), so matches here
# are the set of pages that were actually retrieved.
_CHUNK_HEADER_PAGE_RE = re.compile(r"\bPage:\s*(\d+)\b")
# Teacher-facing full book titles. Responses SHOULD cite these verbatim
# when they cite a book; the internal shorthand ("Teal book", "K-2 book")
# is Smekens jargon that confuses teachers reading the response.
_TEAL_FULL_TITLE_RE = re.compile(
    r"\blaunching\s+the\s+writer'?s?\s+workshop\s+3[-\s]?12\b", re.IGNORECASE
)
_K2_FULL_TITLE_RE = re.compile(
    r"\blaunching\s+the\s+writer'?s?\s+workshop\s+k[-\s]?2\b", re.IGNORECASE
)
# Shorthand forms we explicitly don't want to see in teacher-facing
# responses. Flagged so the scrubber can strip them even when they happen
# to coincide with a real retrieved chunk — the full title is always
# better. Word "book" after the shorthand disambiguates attribution usage
# from incidental mentions (e.g., "K-2 students" as a grade band).
_TEAL_SHORTHAND_RE = re.compile(r"\bteal\s+book\b", re.IGNORECASE)
_K2_SHORTHAND_RE = re.compile(r"\bk[-\s]?2\s+book\b", re.IGNORECASE)


# Markdown emphasis / inline-code markers that can wrap a citation.
_EMPH = r"\*{1,3}|`+|_{1,3}"

# THE page-removal pattern. Compiled ONCE at import (it depends on no runtime
# argument — only the keep/remove DECISION does) and built around the shared
# PAGE_TOKEN, so it strips exactly the forms the validator can see.
#
# Emphasis handling (defect part 3). Removal used to be emphasis-blind: it cut
# "page 66" out of "**page 66**" and shipped "** **" — a blank emphasis slot —
# to the teacher. The fix is symmetric, not a post-hoc cleanup of empty
# markers (which would corrupt "**bold** **also bold**"): an opening marker is
# consumed ONLY IF the SAME marker closes immediately after the citation, via a
# conditional backreference. So:
#
#   "**page 66**"                  -> the markers wrap the citation ALONE, both
#                                     are consumed, nothing is left behind.
#   "**Model this on page 66 ok.**"-> the markers wrap the SENTENCE, the
#                                     conditional fails, they are left alone
#                                     and the teacher's bold run survives.
#
# Two slots (emph_out / emph_in) because the wrap may sit either side of the
# preposition — "**on page 66**" and "on **page 66**" are both natural.
#
# Every whitespace token is [^\S\n] (horizontal only), never \s: \s matches
# "\n", so a boundary around a REMOVED citation would swallow an adjacent
# "\n\n" paragraph break (Brady non-negotiable #11) when the citation sits at
# a paragraph end. Citations are single-line tokens; the pattern must stay on
# one line so a removal can never consume a line break.
_PAGE_SCRUB_RE = re.compile(
    rf"{_H}*"
    rf"(?P<emph_out>{_EMPH})?{_H}*"
    # Optional leading preposition/verb, so removing a citation leaves no
    # dangling "on"/"at"/"see". It carries the SAME _LEFT_GUARD as _PAGE_WORD:
    # unguarded it matched INSIDE a word ("wh|at page 2", "less|on page 2") and
    # the scrubber ate the word's tail along with the citation. That shipped —
    # drive-cache session 496f0423 delivered 'Then I wonder wh should be.' to a
    # teacher inside a read-aloud script. The guard belongs on every token this
    # pattern may consume, not just the page word.
    rf"(?:{_LEFT_GUARD}(?:on|at|see){_H}+)?"
    rf"(?P<emph_in>{_EMPH})?"
    rf"{PAGE_TOKEN}"  # the citation — shared grammar
    # optional trailing "of the X book" so the removal leaves no dangling scaffold
    rf"(?:{_H}*(?:of|in|from){_H}+the{_H}+[A-Za-z0-9 /\-]{{1,40}}?{_H}+book)?"
    rf"(?(emph_in)(?P=emph_in))"
    rf"{_H}*(?(emph_out)(?P=emph_out))"
    rf"{_H}*",
    re.IGNORECASE,
)


def _retrieved_pages(retrieved_context: str) -> set[int]:
    """Pages that chunk headers in retrieved_context declare."""
    return {int(m) for m in _CHUNK_HEADER_PAGE_RE.findall(retrieved_context or "")}


def _token_pages(match: "re.Match[str]") -> set[int]:
    """The page number(s) ONE PAGE_TOKEN match cites — 1, or 2 for a range."""
    return {
        int(g)
        for g in (match.group("pg_n1"), match.group("pg_n2"))
        if g is not None
    }


def _cited_pages(response_text: str) -> set[int]:
    """Page numbers the response text cites — 'page N' / 'p. N' / 'pg. N' /
    'pages N-M', under any separator the shared PAGE_TOKEN grammar admits."""
    return {
        n
        for m in _CITED_PAGE_RE.finditer(response_text or "")
        for n in _token_pages(m)
    }


def scrub_unverifiable_citations(
    text: str,
    retrieved_context: str,
) -> tuple[str, list[str]]:
    """Strip any citation the response couldn't have earned from retrieval.

    Citations are conservative: only keep what's verifiable against the
    retrieved context. This is the deterministic fallback that ships clean
    text when the generator invented a page or book name. Policy principle:
    it is better to stay silent than to cite wrong.

    Scrubbing rules:

      * ``page N`` (and ``p. N`` / ``pg. N``) where N is NOT in the
        retrieved-chunk ``Page:`` headers → removed along with any
        adjacent prepositional phrase ("on page 113", "at p. 113 of
        the Teal book") so the surrounding sentence stays grammatical.

      * ``Teal book`` / ``Teal / K-2 book`` attributions when no Teal
        chunk was retrieved → removed.

      * ``K-2 book`` attributions when no K-2 chunk was retrieved →
        removed.

      * ``digital resources`` mentions when no Launch chunk was
        retrieved → the enclosing sentence removed (the phrase only
        makes sense tied to a real book, not on its own).

    Returns (scrubbed_text, list_of_removed_fragments) so observability
    can log the deterministic cleanup separately from the generator's
    own output.
    """
    if not text:
        return text, []

    scrubbed = text
    removed: list[str] = []

    ctx = retrieved_context or ""
    ctx_lower = ctx.lower()
    launch_in_ctx = _launch_chunk_in_context(ctx)
    has_teal_chunk = "lww312" in ctx_lower or "source: 3-12" in ctx_lower
    has_k2_chunk = "source: k2-" in ctx_lower
    retrieved_pages = _retrieved_pages(ctx)

    def _record(m: "re.Match[str]") -> str:
        removed.append(m.group(0))
        return ""

    # --- Page citations -------------------------------------------------------
    # The pattern (_PAGE_SCRUB_RE) is module-level and built from the shared
    # PAGE_TOKEN grammar — see its definition for the separator/emphasis/
    # newline reasoning. Only the keep-or-remove DECISION is per-call, so only
    # it lives here.
    #
    # Keep ONLY when every page the token cites is in retrieved_pages. A range
    # ("pages 64-65") cites TWO pages, and BOTH must be verified — otherwise an
    # unverifiable page rides along on a verified neighbour. When nothing was
    # retrieved there is nothing to verify against, so every page citation goes.
    def _page_repl(m: "re.Match[str]") -> str:
        if retrieved_pages and _token_pages(m) <= retrieved_pages:
            return m.group(0)  # verified — keep, byte-identical
        removed.append(m.group(0).strip())
        return " "

    scrubbed = _PAGE_SCRUB_RE.sub(_page_repl, scrubbed)

    # --- Book-name attributions ----------------------------------------------
    # Two removal layers:
    #
    # (1) Internal shorthand ("Teal book", "K-2 book", "Teal / K-2 book")
    #     is removed UNCONDITIONALLY. Responses for teachers must use the
    #     full title; the color-code / grade-band shorthand is Smekens-
    #     internal jargon that looks wrong on a teacher-facing surface.
    #
    # (2) Full titles ("Launching the Writers Workshop 3-12", "Launching
    #     the Writers Workshop K-2") are removed only when the matching
    #     book wasn't in the retrieved context — otherwise they're the
    #     correct attribution and should stay.
    # Same [^\S\n] discipline as page_pattern: book-name attributions are
    # single-line phrases, and their boundary/interior whitespace must never
    # match "\n" or a removal at a paragraph end would eat the break. The
    # grade-band separator [\s-] becomes (?:[^\S\n]|-) so "K-2"/"K 2"/"K2"
    # still match but "K\n2" (a split across a break) does not.
    scrubbed = re.sub(
        r"[^\S\n]*(?:\bthe[^\S\n]+)?\bteal(?:[^\S\n]*/[^\S\n]*k(?:[^\S\n]|-)?2)?[^\S\n]+book\b[^\S\n]*",
        _record,
        scrubbed,
        flags=re.IGNORECASE,
    )
    scrubbed = re.sub(
        r"[^\S\n]*(?:\bthe[^\S\n]+)?\bk(?:[^\S\n]|-)?2[^\S\n]+book\b[^\S\n]*",
        _record,
        scrubbed,
        flags=re.IGNORECASE,
    )
    if not has_teal_chunk:
        scrubbed = re.sub(
            r"[^\S\n]*\blaunching[^\S\n]+the[^\S\n]+writer'?s?[^\S\n]+workshop[^\S\n]+3(?:[^\S\n]|-)?12\b[^\S\n]*",
            _record,
            scrubbed,
            flags=re.IGNORECASE,
        )
    if not has_k2_chunk:
        scrubbed = re.sub(
            r"[^\S\n]*\blaunching[^\S\n]+the[^\S\n]+writer'?s?[^\S\n]+workshop[^\S\n]+k(?:[^\S\n]|-)?2\b[^\S\n]*",
            _record,
            scrubbed,
            flags=re.IGNORECASE,
        )

    # --- Digital-resources reminder ------------------------------------------
    # Only makes sense tied to a retrieved Launch chunk. When none retrieved,
    # remove the whole sentence containing the phrase so we don't leave a
    # half-sentence fragment.
    if not launch_in_ctx:
        # Match the ONE sentence containing "digital resources" and nothing
        # more. [^.!?\n] excludes newline as well as sentence punctuation, so
        # the match is confined to a single line — it can neither consume a
        # preceding "\n\n" paragraph break nor span into a neighboring
        # paragraph. (The old leading (?<=[.!?])\s+ prefix consumed the
        # whitespace before the sentence, and \s matches "\n", so a sentence
        # sitting just after a paragraph break had its break swallowed.) The
        # leading run naturally starts right after the previous sentence's
        # boundary (period or newline), so no explicit anchor is needed.
        sentence_with_phrase = re.compile(
            r"[^.!?\n]*?\bdigital[^\S\n]+resources\b[^.!?\n]*[.!?]",
            re.IGNORECASE,
        )

        def _sentence_repl(m: "re.Match[str]") -> str:
            removed.append(m.group(0).strip())
            return " "

        scrubbed = sentence_with_phrase.sub(_sentence_repl, scrubbed)

    # --- Whitespace / punctuation cleanup ------------------------------------
    # Empty/space replacements above sometimes leave orphan prepositions
    # ("See " at EOL), double spaces, empty parens, or a dangling ". .". Tidy
    # those artifacts.
    #
    # Gated on `removed`: these cleanups exist ONLY to repair what a removal
    # left behind. If nothing was removed there are no artifacts, so we skip
    # entirely and return the input BYTE-IDENTICAL. This scrubber runs on the
    # full multi-paragraph delivery text (_build_text_outcome / scripted_ml),
    # and an unconditional cleanup rewrites clean text.
    #
    # Character class is [^\S\n] (whitespace but NOT newline), never \s — \s
    # matches "\n", so collapsing runs of \s flattens the "\n\n" paragraph
    # breaks Brady non-negotiable #11 requires. Removals happen inline within
    # a sentence, so the artifacts we clean are always within-line spaces; we
    # must never touch line structure.
    if removed:
        scrubbed = re.sub(r"[^\S\n]{2,}", " ", scrubbed)
        scrubbed = re.sub(r"[^\S\n]+([.,;:!?])", r"\1", scrubbed)
        scrubbed = re.sub(r"\([^\S\n]*\)", "", scrubbed)  # empty parentheses
        scrubbed = re.sub(r"\.[^\S\n]*\.", ".", scrubbed)

    return scrubbed, removed


def validate_book_citation(
    response_text: str,
    retrieved_context: str,
) -> list[str]:
    """Validate citations the response CHOSE to include; never demand one.

    The rule: citations should only appear when the response is drawing
    content from the retrieved Launch book chunks. A greeting, an ack, or
    an off-topic redirect should have no citation — retrieval running is
    not enough to justify a citation. Forcing a citation ("the response
    MUST cite a page") produced hallucinated pages and invented book
    names, which destroy teacher trust: teachers look up the cited page
    in their physical book and don't find the lesson.

    What this function now enforces:

      * Cited page ∈ retrieved pages. If the response mentions "page N"
        but N wasn't on any retrieved chunk, the response invented it —
        flag so the scrubber removes it.

      * "Teal" / "K-2" book names cited only when the corresponding book
        actually appears in the retrieved context. An invented book name
        is the same trust-breaker as an invented page.

      * A citation that's present AT ALL when no Launch chunk was
        retrieved is nonsense — the response is citing something we
        didn't use.

    What this function no longer demands:

      * A page citation when Launch chunks are retrieved.
      * A book-name mention when Launch chunks are retrieved.
      * A "digital resources" reminder.

    Rationale: those demands forced the generator to invent citations
    on non-teaching responses (greetings, acks). Missing citation is
    recoverable (teacher asks "what page?"). Wrong citation is not.
    """
    errors: list[str] = []
    text = response_text or ""
    ctx = retrieved_context or ""
    ctx_lower = ctx.lower()

    launch_in_ctx = _launch_chunk_in_context(ctx)
    has_teal_chunk = "lww312" in ctx_lower or "source: 3-12" in ctx_lower
    has_k2_chunk = "source: k2-" in ctx_lower

    retrieved = _retrieved_pages(ctx)
    cited = _cited_pages(text)

    # --- Invented-page check --------------------------------------------------
    # Only meaningful when we have known retrieved pages to compare against.
    if retrieved and cited:
        invented = sorted(cited - retrieved)
        if invented:
            valid_pages = ", ".join(str(p) for p in sorted(retrieved))
            invented_pages = ", ".join(str(p) for p in invented)
            errors.append(
                f"Cited page(s) {invented_pages} don't match any retrieved "
                f"chunk. The retrieved chunks are on page(s) {valid_pages}. "
                f"Remove the invented page reference — better to omit than "
                f"to cite wrong."
            )

    # --- Invented-book-name check ---------------------------------------------
    # Two separate failures caught here:
    #
    #   (a) Full title used but the matching book wasn't actually retrieved —
    #       e.g., response says "Launching the Writers Workshop 3-12" but
    #       retrieval returned only K-2 chunks. That's attribution to a book
    #       we didn't pull from.
    #
    #   (b) Internal shorthand "Teal book" / "K-2 book" used at all —
    #       regardless of what was retrieved. Responses are for teachers,
    #       who recognize the full title from their shelves; the color-code
    #       shorthand is Smekens-internal and confuses readers. Flag so the
    #       scrubber strips it and the prompt learns to avoid it.
    if _TEAL_FULL_TITLE_RE.search(text) and not has_teal_chunk:
        errors.append(
            "Response cites 'Launching the Writers Workshop 3-12' but no "
            "Launching 3-12 chunk was retrieved. Don't attribute content "
            "to a book we didn't actually pull from — remove the title."
        )
    if _K2_FULL_TITLE_RE.search(text) and not has_k2_chunk:
        errors.append(
            "Response cites 'Launching the Writers Workshop K-2' but no "
            "K-2 chunk was retrieved. Don't attribute content to a book "
            "we didn't actually pull from — remove the title."
        )
    if _TEAL_SHORTHAND_RE.search(text):
        errors.append(
            "Response uses the internal shorthand 'Teal book'. Cite the "
            "full title 'Launching the Writers Workshop 3-12' instead — "
            "teachers recognize the full title, not the color code."
        )
    if _K2_SHORTHAND_RE.search(text):
        errors.append(
            "Response uses the internal shorthand 'K-2 book'. Cite the "
            "full title 'Launching the Writers Workshop K-2' instead — "
            "teachers recognize the full title, not the grade-band code."
        )

    # --- Citation-without-any-launch-chunk check ------------------------------
    # Response has a "page N" or a Launch-book name but retrieval surfaced no
    # Launch content. That citation can only be an invention.
    if not launch_in_ctx:
        if cited:
            errors.append(
                "Response cites a page but no Launch book chunk was "
                "retrieved. Remove the page reference — there's no source "
                "to tie it to."
            )
        if "digital resources" in text.lower():
            errors.append(
                "Response mentions the book's 'digital resources' but no "
                "Launch book chunk was retrieved. Remove that reference."
            )

    return errors
