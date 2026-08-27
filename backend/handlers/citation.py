"""Deterministic soft book-citation construction (Brady Fm5).

Builds the teacher-facing "If you have the '<book>' book, you'll find this
lesson on p.N." pointer from TYPED chunk metadata — never by asking the LLM to
reformat raw "Book:/Page:" context headers (the reverted Fm5 attempt did that
and leaked the header label words + blank page slots). ONE template, ONE place:
a demo reword is a one-line change to build_soft_citation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


#: Bounded location-lookup phrasings for ``is_location_lookup``. A FIXED set — a
#: page question or a "where in the book" question — NEVER a general classifier.
#: Case-insensitive. The what/which-page forms admit the plural ("what pages")
#: for robustness in the silence-safe direction. The two "... in the book"
#: forms use ``[^?.!\n]*`` (any run that does not cross a sentence boundary) so
#: they match "where is it in the book?" without matching across two separate
#: sentences.
_LOCATION_LOOKUP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwhat\s+pages?\b",           # "what page is that lesson on?", "what page?", "on what page"
        r"\bwhich\s+pages?\b",          # "which page is it on?"
        r"\bwhat'?s\s+the\s+pages?\b",  # "what's the page?"
        r"\bpage\s+number\b",           # "what's the page number?"
        r"\bwhere\s+can\s+i\s+find\b",  # "where can I find that in the book?"
        r"\bwhere\s+do\s+i\s+find\b",   # "where do I find it?"
        r"\bwhere\s+in\s+the\s+book\b",             # "where in the book is that?"
        r"\bwhere\b[^?.!\n]*\bin\s+the\s+book\b",   # "where is it in the book?"
        r"\bfind\b[^?.!\n]*\bin\s+the\s+book\b",    # "find that in the book"
    )
)


def is_location_lookup(message: str) -> bool:
    """True when ``message`` asks WHERE something is — a page / "where in the
    book" lookup ("what page is that on?", "where can I find it in the book?")
    — as opposed to a CONTENT follow-up ("go deeper on that", "make it more
    rigorous", "tell me more about the pizza table").

    Bounded by construction: it matches a FIXED set of location-lookup
    phrasings (``_LOCATION_LOOKUP_PATTERNS``), never a general classifier. It
    exists so a deictic page-lookup FOLLOW-UP can be kept from emitting a
    citation resolved off this turn's referent-less retrieval — the generic
    chunks (a paraphrase, the TOC) that would otherwise print a CONFIDENT WRONG
    page right after the model hedged it "can't confirm the exact page" (bug
    C2). Erring toward matching (silence) is the Brady-safe direction: "better
    to stay silent than lie." Content follow-ups must NOT match, or a citation
    Brady's approved outlines carry would be silenced.
    """
    if not message:
        return False
    return any(p.search(message) for p in _LOCATION_LOOKUP_PATTERNS)


def build_soft_citation(book_title: Optional[str], pages: int | list[int] | None) -> str:
    """The single Fm5 citation template. Returns "" unless BOTH the book title
    and at least one page are known — Fm5 is silent otherwise (better silent
    than wrong; an empty page slot is what shipped as "on ** **" in the reverted
    attempt).

    ``pages`` accepts a scalar (retrieval/library_precheck.py passes one) or a
    list. A list renders in Brady's OWN plural form — image39 point 3 cites
    "pages 97, 111" on one claim and he called that response "all great" — so a
    claim built from two lessons of one book stays ONE sentence rather than
    repeating the title. The single-page output is byte-identical to the shipped
    template: it is approved wording, and test_citation.py locks it.

    Page ORDER is the caller's: this is a pure formatter and does not sort or
    de-duplicate. The caller that assembles the list knows whether the order is
    by relevance or by page, and silently rewriting its input here would hide an
    upstream selection bug rather than surface it.
    """
    if not book_title or pages is None:
        return ""
    # Ask "is this a collection?", never "is this an int?". A str is iterable,
    # so an int-typed test drops "64" into the plural branch and iterates its
    # CHARACTERS -> "pages 6, 4." — malformed, and silent about it. Nothing
    # upstream guarantees the int: ml_library.py:79 passes d.get("page_number")
    # through uncoerced and LibraryEntry is a dataclass (its Optional[int] is an
    # annotation, unenforced at runtime), while library_precheck.py:472 is the
    # one caller NOT gated by the set[int] page-in-context check that makes a
    # stray string fail toward silence elsewhere. Typing the branch by the shape
    # we actually special-case (a sequence of pages) keeps any scalar the data
    # hands us rendering as p.<value> — right for an int, harmless for a string.
    page_list = list(pages) if isinstance(pages, (list, tuple)) else [pages]
    page_list = [p for p in page_list if p is not None]
    if not page_list:
        return ""
    if len(page_list) == 1:
        where = f"p.{page_list[0]}"
    else:
        where = "pages " + ", ".join(str(p) for p in page_list)
    return f"If you have the '{book_title}' book, you'll find this lesson on {where}."


# ===========================================================================
# CLAIM <-> CHUNK IDENTITY — is the marked chunk the lesson the claim is about?
# ===========================================================================
#
# Provenance ("the chunk's page is in this turn's retrieved set") is NOT
# identity. On a bare follow-up ("4th grade") retrieval drifts: the lesson the
# teacher is really asking about is ABSENT, the model describes it from memory,
# and marks the nearest retrieved DECOY. Its page is legitimately in context, so
# a provenance-only gate ships a confident WRONG page (measured on recert-P09:
# a pizza-table claim marked a "one rubric for all writing units" overview and
# cited its p.57). The corroboration below is the missing check.
#
# It is deliberately NARROW because OVER-suppression of correct cites is the
# real risk (Brady wants the citation when it is right). It suppresses ONLY when
# the chunk carries a determinable lesson identity that the claim fails to
# mention. A chunk whose id has no distinctive tokens is indeterminate -> the
# gate cannot prove a mismatch -> it does not fire (fails toward CITING). Fail
# direction on a proven mismatch is SILENCE — Brady's "better silent than a
# wrong page", the same direction as the empty-chunks / page-not-in-context
# gates already here.

_TRIGGERS_PATH = Path(__file__).resolve().parent.parent / "data" / "skill_triggers.json"

#: Generic connective / classroom words that appear across many lessons and
#: claims. Filtered from BOTH sides so a shared generic word ("writing", "all",
#: "grade") can never bridge a decoy chunk to an unrelated claim. Natural
#: (unstemmed, mostly singular) forms — ``_identity_tokens`` checks a token
#: against this set both raw and stemmed, so a plural is caught too. Distinctive
#: lesson words (rubric, detail, sentence, paragraph, introduction, snapple, ...)
#: are deliberately absent.
_IDENTITY_STOPWORDS: frozenset[str] = frozenset({
    # articles / conjunctions / prepositions / pronouns / aux
    "the", "and", "or", "of", "to", "for", "with", "at", "by", "per", "vs",
    "versus", "into", "from", "about", "as", "that", "this", "these", "those",
    "its", "was", "are", "were", "your", "you", "their", "them", "they", "our",
    "his", "her", "one", "two", "first", "off",
    # generic pedagogy / classroom / structural-slug words
    "lesson", "strategy", "strategies", "skill", "teach", "teaching", "teacher",
    "student", "kid", "child", "children", "writer", "writing", "write",
    "written", "grade", "band", "book", "page", "section", "overview", "intro",
    "use", "using", "used", "class", "classroom", "whole", "group", "all",
    "how", "when", "where", "what", "which", "day", "week", "unit", "mini",
    "step", "part", "level", "pacing", "toc", "help", "helping", "make", "start",
    "add", "adding", "show", "give", "get", "more", "most", "new", "good",
    "great", "see", "want",
    "need", "like", "some", "each", "few", "then", "there", "still", "same",
    "here", "way", "idea", "point", "thing", "lot", "teal", "ccss", "lww", "pdf",
})


#: content_types that are NOT a single lesson — a book overview, a pacing guide,
#: a whole-book rubric all live under "textbook_overview". Citing one as "this
#: LESSON on p.N" is a category error, and on a drifted follow-up it is exactly
#: how a wrong page ships: its all-stopword slug ("overview how to use",
#: "pacing grades 3-5") is identity-INDETERMINATE, so the token/trigger check
#: below would fail toward CITING. Suppress the type up front (recert-P09 cited
#: overview-how-to-use p.4 + pacing p.5). Marker path only — SCRIPTED_ML cites
#: its own lesson's source_chunk_id (claim_text=None), never one of these.
_NON_LESSON_CITE_TYPES: frozenset[str] = frozenset({"textbook_overview"})


def _norm_identity(text: str) -> str:
    """Lowercase; fold hyphens/underscores/slashes/punctuation to spaces;
    collapse runs. Turns a chunk slug ('table-top-leg-sentences') and teacher
    prose ('pizza-table / table-top') into the same space-separated word stream
    the trigger phrases and token sets are compared over."""
    if not text:
        return ""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _stem(token: str) -> str:
    """Drop a single trailing plural 's' (len > 3, not '...ss') so 'sentences'
    matches 'sentence', 'details' matches 'detail'. Not a linguistic stemmer —
    just enough to keep singular/plural from splitting an identity."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _identity_tokens(text_norm: str) -> set[str]:
    """Distinctive (stemmed) identity tokens of already-normalised text: drop
    anything holding a digit (page/section/id fragments — s8, ml05, lww312,
    '3-12'), anything shorter than 3 chars, and the generic stopwords."""
    out: set[str] = set()
    for raw in text_norm.split():
        if any(ch.isdigit() for ch in raw) or len(raw) < 3:
            continue
        tok = _stem(raw)
        if raw in _IDENTITY_STOPWORDS or tok in _IDENTITY_STOPWORDS:
            continue
        out.add(tok)
    return out


_TRIGGER_INDEX: Optional[dict[str, tuple[str, ...]]] = None


def _trigger_index() -> dict[str, tuple[str, ...]]:
    """canonical trigger -> its naming phrases (canonical name + synonyms),
    each normalised. Lazily loaded from data/skill_triggers.json — the SAME
    synonym map retrieval uses, so 'pizza table' (teacher) and
    'table-top-leg-sentences' (slug) both resolve to the pizza-table trigger.

    ``related_skills`` is deliberately NOT indexed: those are broad query terms
    ('paragraph writing'), useful for boosting retrieval but too loose for an
    identity check that must be able to REJECT a drifted decoy."""
    global _TRIGGER_INDEX
    if _TRIGGER_INDEX is None:
        idx: dict[str, tuple[str, ...]] = {}
        try:
            data = json.loads(_TRIGGERS_PATH.read_text())
        except (FileNotFoundError, ValueError):
            data = {}
        for canon, entry in data.get("triggers", {}).items():
            phrases = {_norm_identity(canon)}
            syns = entry.get("synonyms", []) if isinstance(entry, dict) else []
            for syn in syns:
                phrases.add(_norm_identity(syn))
            idx[canon] = tuple(p for p in phrases if p)
        _TRIGGER_INDEX = idx
    return _TRIGGER_INDEX


def _triggers_named_in(text_norm: str) -> set[str]:
    """Canonical triggers whose name or a synonym appears — word-bounded — in
    ``text_norm``. Word-bounded via space padding: a phrase matches only on
    whole-word boundaries, never as a substring of a longer word."""
    if not text_norm:
        return set()
    padded = f" {text_norm} "
    found: set[str] = set()
    for canon, phrases in _trigger_index().items():
        if any(f" {p} " in padded for p in phrases):
            found.add(canon)
    return found


def _corroborates_identity(chunk: Any, claim_text: str) -> bool:
    """True when the marked ``chunk`` is corroborated as the lesson ``claim_text``
    is about — a shared Smekens trigger (via the synonym map) OR a shared
    distinctive lesson token.

    The chunk's identity comes from its ``chunk_id`` slug, ``skill_title`` and
    ``strategy_name`` (the raw-token side) plus its ``lesson_trigger`` tags (the
    trigger side only — a tag is a canonical name, not free text to word-match).
    ``content`` is NOT used: the full lesson body would match almost any claim
    and defeat the gate.

    Returns True (does not suppress) when the chunk's identity is indeterminate
    or the claim is empty — silence is only for a PROVEN mismatch."""
    if not claim_text or not claim_text.strip():
        return True

    # A book overview / pacing / rubric page is never "this lesson" — suppress it
    # up front, before the identity-token check (whose all-stopword-slug
    # "indeterminate -> allow" default is exactly what let recert-P09 cite the
    # p.4 "how to use" overview and the p.5 pacing guide for a pizza-table claim).
    if ((getattr(chunk, "content_type", "") or "").strip().lower()
            in _NON_LESSON_CITE_TYPES):
        return False

    slug = getattr(chunk, "chunk_id", "") or ""
    skill_title = getattr(chunk, "skill_title", "") or ""
    strategy = getattr(chunk, "strategy_name", "") or ""
    tags = getattr(chunk, "lesson_trigger", None) or []

    chunk_raw_norm = _norm_identity(f"{slug} {skill_title} {strategy}")
    tag_norm = _norm_identity(" ".join(str(t) for t in tags))

    chunk_triggers = _triggers_named_in(chunk_raw_norm) | _triggers_named_in(tag_norm)
    chunk_tokens = _identity_tokens(chunk_raw_norm)

    # No determinable identity -> cannot prove a mismatch -> allow the cite.
    if not chunk_triggers and not chunk_tokens:
        return True

    claim_norm = _norm_identity(claim_text)
    if chunk_triggers and (_triggers_named_in(claim_norm) & chunk_triggers):
        return True
    if chunk_tokens and (_identity_tokens(claim_norm) & chunk_tokens):
        return True
    return False


def resolve_attribution(
    chunk_id: Optional[str],
    chunks: list[Any] | None,
    retrieved_context: str,
    claim_text: Optional[str] = None,
) -> Optional[tuple[str, int]]:
    """Resolve the ONE source the GENERATOR named into (full_title, page).

    Why this exists instead of ranking (see the spec): the citation used to be
    chosen from retrieval RANK, BEFORE generation ran — so "you'll find THIS
    LESSON on p.N" was picked before "this lesson" existed (measured: cited page
    == top chunk's page, 30/30). The deleted `select_citation_source` stated the
    premise this disproves — "retrieval is Launch-first, so the first qualifying
    chunk is the most relevant lesson" — which held only until an attractor
    outranked the lesson actually taught. The model reads "Source: <chunk_id>"
    on every block (assembler.py:79) and is the only thing that knows which one
    it taught from. So it points; we speak.

    Silence is by construction, not by confidence (Brady: "better to stay silent
    than lie" — our phrase, which he endorsed). Returns None unless ALL hold:
    the model named an id · the id is in THIS turn's retrieved set (a fabricated
    id resolves to nothing) · the chunk has a full book title · it has a page ·
    that page appears in the assembled context's "Page:" headers.

    The page-in-context check is retained from Fm5 (8f2c6ef made it strict): it
    keeps the citation agreeing with validate_book_citation and surviving
    scrub_unverifiable_citations.

    Matching is exact: an id the caller could not extract cleanly resolves to
    nothing, which fails toward silence rather than toward a confident wrong
    page.

    The ONLY way this system picks a source now. SCRIPTED_ML resolves the id the
    lesson names (`MiniLesson.source_chunk_id`); HOW_TO_TEACH + COACHING resolve
    the ids the generator marked its claims with, via `resolve_markers` below.
    Nothing selects by rank any more.

    ``claim_text`` — the marker path (`resolve_markers`) passes the text of the
    claim the marker sits on, and provenance alone is then not enough: the chunk
    must also be corroborated as the lesson that claim is ABOUT
    (`_corroborates_identity`). This closes the drift defect where a bare
    follow-up re-retrieves the wrong lesson, its page is legitimately in context,
    and the model marks it — a confident WRONG page. When ``claim_text`` is None
    (SCRIPTED_ML, whose whole lesson is the claim and which has no per-line text)
    the identity gate is OFF and behaviour is byte-identical to before.
    """
    if not chunk_id:
        return None
    from retrieval.assembler import _full_book_title
    from validation.citations import _retrieved_pages

    retrieved_pages = _retrieved_pages(retrieved_context)
    for chunk in chunks or []:
        if getattr(chunk, "chunk_id", None) != chunk_id:
            continue
        title = _full_book_title(chunk)
        page = getattr(chunk, "page_number", None)
        if title and page is not None and page in retrieved_pages:
            # IDENTITY gate (marker path only): provenance is satisfied, but is
            # this chunk the lesson the claim is about? A drifted decoy fails
            # here -> silence, the same fail-direction as the checks above.
            if claim_text and not _corroborates_identity(chunk, claim_text):
                return None
            return title, page
        # Named chunk found but not citeable — silence, never a fallback to
        # another chunk. Falling back to rank is the defect this replaces.
        return None
    return None


# ===========================================================================
# PER-CLAIM markers — the markdown half of "the model points, the code speaks"
# ===========================================================================
#
# Brady's own approved responses carry citations PER CLAIM, not one per turn:
# image39 point 3 cites "pages 97, 111" on a single claim, and another of his
# artifacts carries 5 citation sites across 6 pages. We ship exactly ONE footer
# (measured: max = min = 1 across 25 live turns). Retrieval is NOT the
# constraint — every page his artifacts cite is already in the retrieved
# context on every run. The missing piece is the ability to attach a citation
# to the CLAIM that earned it, which is what this resolver provides.

#: What the model is ASKED to emit. Exact ids only — this is the grammar the
#: prompt promises and the only shape resolve_attribution can match. Verified
#: against the corpus: all 710 chunk ids match this class, so a well-formed
#: marker naming a real chunk is always captured.
_MARKER_RE = re.compile(r"\[\[src:(?P<cid>[A-Za-z0-9._-]+)\]\]")

#: What the SWEEP removes. DELIBERATELY WIDER than _MARKER_RE and NOT derived
#: from it.
#:
#: scrub_unverifiable_citations runs BEFORE this resolver (that order is
#: mandatory — the title-scrubber would strip a citation we had already built;
#: the full rationale lives on _base_text._build_text_outcome, which enforces
#: the order), and its _PAGE_SCRUB_RE rewrites
#: `page-01` INSIDE a chunk id to a SPACE:
#:
#:     [[src:ccss-page-01-college-and-career-…]]
#:  -> [[src:ccss- -college-and-career-…]]
#:
#: Measured, not hypothetical: 11 of 710 corpus ids are affected (every
#: `ccss-page-NN-*`). A space is not in _MARKER_RE's class, so a grammar-bound
#: sweep misses exactly those and ships a raw marker to a teacher — breaking
#: the invariant this design's safety argument rests on ("no marker is ever
#: teacher-visible"). No Brady citation is at risk from the mangling itself:
#: those ccss chunks carry book=None, so they resolve to correct silence. The
#: INVARIANT is what breaks.
#:
#: Two patterns that both claim to define a marker WILL drift apart — that
#: divergence IS the bug (the same lesson PAGE_TOKEN records in
#: validation/citations.py). So they are split by CONTRACT instead: the narrow
#: one recognises, the wide one removes, and the wide one is bounded (no
#: newline, ≤200 chars) so it can never run away across a paragraph.
_MARKER_SWEEP_RE = re.compile(r"\[\[src:[^\]\n]{0,200}\]\]")

#: Interior whitespace left where a marker was removed. [^\S\n] (horizontal
#: only) never \s — the same discipline the scrubber documents at length: \s
#: matches "\n", so collapsing it would flatten the "\n\n" paragraph breaks
#: Brady non-negotiable #11 requires.
_INTERIOR_WS_RE = re.compile(r"[^\S\n]{2,}")


def _tidy_after_removal(swept: str) -> str:
    """Close the gap a removed marker left, without touching LEADING
    indentation — markdown nests list items on it, so collapsing the indent
    would silently re-parent a sub-item."""
    lead = swept[: len(swept) - len(swept.lstrip())]
    return lead + _INTERIOR_WS_RE.sub(" ", swept[len(lead):]).rstrip()


def _resolve_one_line(
    line: str,
    chunks: list[Any] | None,
    retrieved_context: str,
    seen: set[str],
) -> str:
    """Resolve every marker on ONE line into citation sentences appended to it.

    Per LINE, and that is load-bearing rather than cosmetic. picklist.py's
    _scan_list_lines ends the list at the first non-list line ("prose after the
    list does end it"), and _base_text.py records offered_skills off the text a
    citation has already entered. So a citation placed on its OWN line mid-list
    truncates the pick-list, "number 4" falls out of range, and the nn4 fix —
    a teacher asking for 4 and silently getting 3 — reverts. A claim is a line;
    its citation joins that line.

    ``seen`` carries the citation sentences already emitted earlier in the
    response, so an identical footer (same title + pageset) repeated on later
    lines is dropped (hygiene (2a)) — kept mutable across lines by the caller.
    """
    swept = _MARKER_SWEEP_RE.sub("", line)
    if swept == line:
        return line  # no marker of any shape → byte-identical, always

    body = _tidy_after_removal(swept)

    # (2b) Never jam a citation after a ":" list lead-in or a "?" closing
    # question — "Here are the skills: <sentence>" and "Does this make sense?
    # <sentence>" both read as noise, and a citation on a list lead-in can
    # truncate the pick-list. The marker is still SWEPT (nothing leaks); we just
    # do not speak a citation onto the colon/question.
    if body.endswith((":", "?")):
        return body

    # Group by TITLE, not by line: one sentence per book, pages joined into
    # Brady's own plural form. Grouping by line instead would name one book
    # while carrying another's page — a citation to a page that does not exist
    # in the book named. ``swept`` (the marker-free claim text) is what the
    # identity gate corroborates each marker against — never the raw line, whose
    # `[[src:<id>]]` text would let the chunk id "corroborate" itself.
    by_title: dict[str, list[int]] = {}
    for m in _MARKER_RE.finditer(line):
        resolved = resolve_attribution(
            m.group("cid"), chunks, retrieved_context, claim_text=swept
        )
        if resolved is None:
            continue  # unresolvable → silence for THIS marker, never a fallback
        title, page = resolved
        pages = by_title.setdefault(title, [])
        # A citation names a LOCATION in a physical book, so the same location
        # named twice is one location. Reachable, not theoretical: 31 of 225
        # Launch (book,page) locations hold more than one chunk, so two
        # legitimately different markers on one claim can land on one page and
        # would otherwise render "on pages 15, 15." De-duplicating belongs here
        # in the selector that ASSEMBLES the list — never in build_soft_citation,
        # which is a pure formatter whose refusal to rewrite its input is what
        # keeps a bug like this visible instead of laundering it.
        if page not in pages:
            pages.append(page)

    # (2c) A physical book reads front-to-back, so a multi-page list ascends —
    # matching Brady's approved "pages 97, 111". Sorting here (the assembler),
    # not in build_soft_citation, keeps that a pure formatter.
    citations = [
        c for c in (build_soft_citation(t, sorted(p)) for t, p in by_title.items()) if c
    ]
    if not citations or not body.strip():
        # A marker with no claim left beside it has nothing to cite. Dropping it
        # is the safe direction twice over: silence is Brady's stated preference
        # over a wrong pointer, and emitting the sentence here would put a
        # citation on its own line — the pick-list truncation above.
        return body

    # (2a) Drop a citation identical to one already emitted earlier in the
    # response (keep the first). Add only what we actually emit to ``seen`` — a
    # citation suppressed for another reason must not block a later real one.
    fresh: list[str] = []
    for c in citations:
        if c in seen:
            continue
        seen.add(c)
        fresh.append(c)
    if not fresh:
        return body
    return " ".join([body, *fresh])


def resolve_markers(
    text: str,
    chunks: list[Any] | None,
    retrieved_context: str,
) -> str:
    """Turn the `[[src:<chunk_id>]]` markers the generator emitted into Brady's
    citation sentences, in place, on the claim that earned each one.

    The plan-(1) seam, extended to markdown: the model POINTS at the source it
    built from (it is the only thing that knows), and code SPEAKS the citation
    from that chunk's typed metadata. The model is never asked to write a book
    title or a page number — the rule the reverted Fm5 prompt-reword broke when
    it leaked `Book:`/`Page:` header labels and blank page slots to teachers.

    Silence is by construction: an unresolvable marker (fabricated id, no page,
    no title, page absent from this turn's context, OR a chunk the claim does
    not corroborate as the lesson it is about) is removed and cites nothing. It
    never falls back to another chunk — falling back to rank is the defect this
    whole design replaces.

    Guarantees, in order of how badly their violation would hurt:

      1. No marker is EVER teacher-visible. The final sweep is unconditional
         and wider than the emission grammar (see _MARKER_SWEEP_RE).
      2. Text carrying no markers is returned byte-identical, so the handlers
         that must stay uncited cannot be disturbed by this running over them.
      3. A citation lands on its claim's line (see _resolve_one_line).
      4. A citation is spoken only for a chunk the claim corroborates as its
         lesson (resolve_attribution's identity gate), never after a ":"/"?"
         line, deduplicated across lines, with any multi-page list ascending.
    """
    if not text:
        return text

    # ``seen`` spans the whole response so an identical footer repeated on
    # several lines is emitted once (hygiene (2a)).
    seen: set[str] = set()
    # keepends=True: a plain splitlines()/"\n".join() round-trip DROPS a
    # trailing newline and rewrites "\r\n" — this function runs over the whole
    # delivered response, so that silent edit would ship.
    out: list[str] = []
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        ending = raw[len(body):]
        out.append(_resolve_one_line(body, chunks, retrieved_context, seen) + ending)

    # Unconditional, whole-text net. The per-line pass already sweeps wide, so
    # this is defence in depth rather than the primary mechanism — kept because
    # the cost is one regex pass and the failure it guards (a raw marker in a
    # teacher's lesson) is unrecoverable trust damage.
    return _MARKER_SWEEP_RE.sub("", "".join(out))
