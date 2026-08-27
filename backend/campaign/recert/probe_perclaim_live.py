"""BEFORE picture for PLAN (2): the PER-CLAIM citation gap on HOW_TO_TEACH +
COACHING.

WHAT THIS MEASURES (read before citing it). Plan (1) fixed WHICH page we cite on
the SCRIPTED_ML path. Plan (2) is about a different axis entirely: HOW MANY
citation sites a response carries and WHERE they sit. Brady's approved artifacts
attach a citation TO EACH CLAIM, inline on the claim's own line:

  image39 (his query, VERBATIM from the user bubble) — FIVE sites, SIX pages:
    intro paragraph                        (…K-2, page 99)
    1. Teach what makes a sentence complete   (silent)
    2. Clarify letters/words/sentences     (…K-2, page 96)
    3. Strengthen sentence conventions     (…K-2, pages 97, 111)   <- 2 pages, 1 site
    4. Expand labels into full sentences   (…K-2, page 99)
    5. Fix incomplete writing (Spider Legs)(…K-2, page 101)

  image3 (RECONSTRUCTED — see below) — TWO sites: his p.64 and his p.124.

We ship exactly ONE footer per response, after the list, before the closer
(`_base_text.py:586` -> `_insert_book_citation`). THAT GAP is what this probe
measures. So the headline is a SHAPE, not just a rate: sites-per-response, and
inline-vs-own-line.

Drive automatically; READ BY HAND. Do NOT add an automatic verdict: N1 forces
"details" where the PIE list says "reasons", so a similarity-argmax judge
manufactures false mismatches (logs.md, 2026-07-17 AM).

------------------------------------------------------------------------------
INHERITED FROM probe_citation_identity_live.py (hard-won; do not regress):

1. ENDPOINT is `/api/chat`, not `/chat` (`routes_v4.py:56` — `APIRouter(prefix="/api")`).

2. THE RESPONSE HAS TWO SHAPES AND ONLY ONE OF THEM HAS `book_citation`.
   `routes_v4.py:198-206` (`_build_response`): `outcome.structured is not None`
   -> the body is a MiniLesson DICT carrying `book_citation`; otherwise the body
   is a markdown STRING and the citation is a FOOTER INSIDE IT. Both handlers
   this probe targets are TEXT handlers (`_base_text.py:592` sets
   `structured=None`), so `.get("book_citation")` yields NOTHING here — the
   mistake that nearly faked plan (1)'s presence rate (20/30 vs the true 30/30).
   EVERY number below is parsed out of the response TEXT.

3. `SourceInfo` CARRIES NO PAGE (the phantom-page finding, `839a051`: 0 of 9,942
   sources ever had one). Do not read a page off `sources`.

4. EVERY REQUEST CARRIES ITS OWN `user_id`. `config.py:85` sets
   `rate_limit_per_hour: int = 50` and `routes_v4.py:86` buckets an absent
   `user_id` to the SHARED literal "anonymous". A 429 mid-drive silently
   truncates the very rate being measured.

WHAT THIS PROBE ADDS OVER ITS PARENT:

5. IT RESOLVES THE CITED PAGE AGAINST THIS TURN'S OWN RETRIEVED CONTEXT, not
   just the offline library. `ChatResponse.retrieved_context` (models.py:125) is
   the assembled context verbatim, and `assembler.py:79-94` puts
   `[N] Source: <chunk_id> | Book: <full title> | Page: <N>` on every block. So
   for any cited page we can show WHAT THAT CHUNK ACTUALLY SAYS, from the same
   turn that cited it. The library (`data/scripted_ml_library.json`) is a second,
   independent resolver — it covers 183 of the Launch pages, so it can come up
   empty where the context does not.

6. PAGES COLLIDE ACROSS THE TWO BOOKS, so every resolution is keyed on
   (book, page) and NEVER on the page alone:
       p.64  Teal = 'Add "leg" sentences per "table-top" reason'  <- Brady's pt 1
             K-2  = 'Draw feelings on faces'
       p.124 Teal = 'Indent for new information'                  <- Brady's pt 4
             K-2  = 'Name the what (opinion) & why (reasons)'
   A resolver keyed on the page alone would call a K-2-at-grade-3 mis-cite
   correct. `_resolve` takes the book as a required argument for that reason.

7. IT HAS A SANITY CASE, AND IT RUNS BEFORE THE DRIVE (`_sanity`, --sanity-only).
   This probe's headline claim is an ABSENCE ("no citation sits inline; there is
   only ever one site"). An extractor that can only recognise our own footer
   template would report exactly that absence NO MATTER WHAT THE APP DID — the
   unfailable-check trap this campaign has now hit seven times in two days. So
   the extractor is first run over a RECONSTRUCTION OF BRADY'S image39 (5 sites,
   6 pages, inline) and image11's page-less prose pointer, and must FIND them.
   If it cannot see a per-claim citation in a text that has five of them, its
   "0 inline" on a live response means nothing and the drive is aborted.
------------------------------------------------------------------------------
"""
import asyncio
import json
import os
import re
import sys
import uuid

import httpx

API = os.environ.get("PROBE_API", "http://127.0.0.1:8000")
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "..", "..", "data", "scripted_ml_library.json")

CASES = [
    # image39 — Brady's query VERBATIM from the user bubble (spec §1.3). His
    # approved response carries 5 citation sites / 6 pages. Pin to it freely.
    ("image39 sentences g2",
     "I'm frustrated that my second graders can't write sentences. What do I do?", "2"),
    # image3 — RECONSTRUCTED. That screenshot has NO user bubble and is a snip of
    # OUR demo, not his session; this query string appears in NONE of the three
    # primaries (spec §5). Its ROUTE is therefore a finding, not an assumption:
    # read `intent` before pinning anything to it. His p.64 + p.124.
    ("image3 paragraphing g3",
     "How do I teach paragraph writing to 3rd graders?", "3"),
    ("how-to-teach leads g5",
     "How do I teach strong leads to 5th graders?", "5"),
    # image11's own question (spec §1.3) — the COACHING turn Brady RED-praised
    # for "the reference to the book" (p87). Its answer had a book title and NO
    # page.
    ("coaching anchor-chart K",
     "What does that anchor chart with the flaps look like?", "K"),
    ("coaching frustrated g2",
     "My second graders can't write sentences and I'm frustrated.", "2"),
]
RUNS = 5

# --- Book vocabulary -------------------------------------------------------
# The two teacher-facing full titles (`assembler.py:39-42` _BOOK_FULL_TITLE) and
# the shorthands an LLM reaches for. Fm5 exists partly to have KILLED the "K-2
# book" shorthand, so the shorthands are matched precisely BECAUSE their presence
# would be a finding.
#
# ORDER MATTERS: longest-first, and the matcher consumes left-to-right without
# overlap, so "Launching the Writers Workshop K-2" is tried before "K-2 book".
# Otherwise the full title's own tail would register as a second, shorthand site.
_BOOK_PATTERNS = [
    (r"Launching the Writer'?s Workshop,?\s*(?:grades\s*)?3-12", "Teal"),
    (r"Launching the Writer'?s Workshop,?\s*(?:grades\s*)?K-2", "K-2"),
    (r"Launching the Writer'?s Workshop", "Launch (unqualified)"),
    (r"\bTeal book\b", "Teal (shorthand)"),
    (r"\bK-2 book\b", "K-2 (shorthand)"),
]
_BOOK_RE = re.compile("|".join(f"({p})" for p, _ in _BOOK_PATTERNS), re.IGNORECASE)
_BOOK_LABELS = [label for _, label in _BOOK_PATTERNS]

# --- Page vocabulary -------------------------------------------------------
# Tolerant on purpose. Our template emits "p.64" (no space), but this probe must
# also see shapes we do NOT emit — Brady's "(…, page 64)" parenthetical, his
# "pages 97, 111" two-page claim, and anything an LLM leaks — or it would only
# ever find our own footer and confirm its own premise (see note 7).
_PAGE_RE = re.compile(
    r"\bp(?:p|ages?|g)?\.?\s*(\d{1,3}(?:\s*(?:,|and|&)\s*\d{1,3})*)\b",
    re.IGNORECASE,
)
# Our ONE shipped Fm5 template (`handlers/citation.py:52`), matched so a site can
# be labelled as OURS vs the model's own prose. Tolerant on quote style: the
# builder emits straight quotes but the text runs through markdown handlers.
_FM5_RE = re.compile(
    r"If you have the ['‘’\"]?(?P<book>[^'‘’\"]+?)['‘’\"]?\s+book,\s*"
    r"you['’]ll find this lesson on p(?:ages?)?\.?\s*(?P<pages>\d[\d,\s]*)",
    re.IGNORECASE,
)


def _load_library():
    """(book_key, page) -> skill_title, from the ML library.

    Keyed on the BOOK as well as the page (note 6). Returns {} rather than
    raising: a missing library must degrade the hand-reading aid, never kill the
    drive.
    """
    try:
        with open(_LIB) as f:
            entries = json.load(f)["entries"]
    except (OSError, KeyError, json.JSONDecodeError):
        return {}
    out = {}
    for e in entries:
        doc = (e.get("source_document") or "")
        if "3-12" in doc:
            book = "Teal"
        elif "K-2" in doc:
            book = "K-2"
        else:
            continue
        page = e.get("page_number")
        if page is None:
            continue
        out.setdefault((book, page), e.get("skill_title"))
    return out


_LIBRARY = _load_library()


def _book_key(name):
    """Normalise any book mention to 'Teal' | 'K-2' | None. The single place the
    two books are told apart; everything keyed on a book goes through it."""
    if not name:
        return None
    n = name.lower()
    if "3-12" in n or "teal" in n:
        return "Teal"
    if "k-2" in n:
        return "K-2"
    return None


def _find_book_mentions(text):
    out = []
    for m in _BOOK_RE.finditer(text):
        # Which alternative fired -> which label. lastindex is the 1-based group.
        idx = (m.lastindex or 1) - 1
        out.append({
            "kind": "book",
            "start": m.start(),
            "end": m.end(),
            "raw": m.group(0),
            "label": _BOOK_LABELS[idx],
            "book": _book_key(m.group(0)),
        })
    return out


def _find_page_mentions(text):
    out = []
    for m in _PAGE_RE.finditer(text):
        nums = [int(n) for n in re.findall(r"\d{1,3}", m.group(1))]
        out.append({
            "kind": "page",
            "start": m.start(),
            "end": m.end(),
            "raw": m.group(0),
            "pages": nums,
        })
    return out


def _line_bounds(text):
    """[(start, end, line_index, line_text)] over the response, so a mention can
    be placed on its line — placement is the whole point of this probe."""
    bounds, pos = [], 0
    for i, line in enumerate(text.split("\n")):
        bounds.append((pos, pos + len(line), i, line))
        pos += len(line) + 1
    return bounds


def _line_of(pos, bounds):
    for start, end, i, line in bounds:
        if start <= pos <= end:
            return i, line, start
    return -1, "", 0


_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _classify_placement(site, line_text, line_start):
    """inline_with_claim | own_line — measured, not assumed.

    Strip the site's own span out of its line, then strip the list marker and
    markdown emphasis. If SUBSTANTIVE claim text remains, the citation is sitting
    inline within a claim (Brady's shape). If nothing meaningful remains, the
    citation occupies the line by itself (our shape).

    The 15-char floor is deliberate and is the one judgement call here: it keeps
    a stray bullet glyph or a stranded "and" from reading as a claim. Brady's
    shortest cited claim ("2. Clarify letters/words/sentences") is 33 chars of
    remainder, and our footer's remainder is 0, so nothing real sits near the
    boundary. `remainder` is recorded verbatim so a hand-reader can overrule it.
    """
    rel_start = site["start"] - line_start
    rel_end = site["end"] - line_start
    remainder = (line_text[:rel_start] + " " + line_text[rel_end:])
    remainder = _LIST_MARKER_RE.sub("", remainder)
    remainder = remainder.replace("*", "").replace("_", "").replace("#", "")
    # Brady's form is "claim text (Book, page N)" — the parens belong to the
    # citation, not the claim, so an empty-but-for-punctuation remainder is NOT a
    # claim.
    remainder = re.sub(r"[\s(),.;:—–-]+", " ", remainder).strip()
    letters = sum(c.isalpha() for c in remainder)
    return ("inline_with_claim" if letters >= 15 else "own_line"), remainder


def _extract_sites(text):
    """Group book/page mentions into CITATION SITES.

    A site = one place in the text that points at a book and/or a page. Brady's
    image39 has five (one of them carrying two pages: "pages 97, 111"); we ship
    one. Mentions are clustered when they sit on the SAME LINE within a 160-char
    window — which is what makes "(Launching the Writers Workshop K-2, pages 97,
    111)" ONE site rather than two, and keeps two separately-cited list items on
    adjacent lines from collapsing into one.

    A book with no page IS a site (image11's praised form is exactly that:
    "check the 'Launching the Writers Workshop K-2' book and its digital
    resources" — book, no page). A bare page with no book is also a site: it is
    how a leak would look.
    """
    mentions = sorted(_find_book_mentions(text) + _find_page_mentions(text),
                      key=lambda m: m["start"])
    # Drop book mentions swallowed by a longer, earlier book mention (the
    # longest-first ordering means the full title wins; its "K-2" tail must not
    # re-register as a shorthand site).
    deduped, last_end = [], -1
    for m in mentions:
        if m["kind"] == "book" and m["start"] < last_end:
            continue
        if m["kind"] == "book":
            last_end = m["end"]
        deduped.append(m)

    bounds = _line_bounds(text)
    sites, current = [], []

    def _flush():
        if not current:
            return
        start = min(m["start"] for m in current)
        end = max(m["end"] for m in current)
        line_i, line_text, line_start = _line_of(start, bounds)
        placement, remainder = _classify_placement(
            {"start": start, "end": end}, line_text, line_start
        )
        books = [m["book"] for m in current if m["kind"] == "book"]
        pages = [p for m in current if m["kind"] == "page" for p in m["pages"]]
        raw = text[start:end]
        sites.append({
            "start": start,
            "end": end,
            "raw": raw,
            "line_index": line_i,
            "line_text": line_text,
            "books": books,
            "book": books[0] if books else None,
            "book_raw": next((m["raw"] for m in current if m["kind"] == "book"), None),
            "pages": pages,
            "n_pages": len(pages),
            "placement": placement,
            "line_remainder": remainder,
            # Is this OUR deterministic Fm5 footer, or the model's own prose?
            # The distinction is the whole of the COACHING double-mention
            # question, and it cannot be recovered by eye from a count.
            "is_fm5_template": bool(_FM5_RE.search(line_text)),
        })
        current.clear()

    for m in deduped:
        if current:
            same_line = _line_of(m["start"], bounds)[0] == _line_of(current[-1]["start"], bounds)[0]
            near = m["start"] - current[-1]["end"] <= 160
            if not (same_line and near):
                _flush()
        current.append(m)
    _flush()
    return sites


_BLOCK_HEAD_RE = re.compile(r"^\[(\d+)\]\s*(Source:.*)$", re.MULTILINE)


def _parse_retrieved_blocks(retrieved_context):
    """[{index, chunk_id, book, page, head}] from the assembled context.

    Parsing it gives the ONE thing the envelope's `sources` cannot (note 3): the
    page, plus the chunk text that page actually holds — so a cited page can be
    checked against what THIS turn retrieved, by hand.

    ⚠️ THE HEADER IS A ` | `-JOINED key: value LIST, AND THE KEYS ARE OPTIONAL.
    `assembler.py:79-94` appends Source · Type · Grade · Trait · Mode · Book ·
    Page, each only when the chunk carries it. The first version of this parser
    was a POSITIONAL regex expecting `Source: <id> | Book: <t> | Page: <N>`
    adjacent — written from this probe's author reading only the Book/Page half
    of `_format_chunk` — so the real header
        [1] Source: lww312-… | Type: textbook_lesson | Grade: 3-12 | Trait: Ideas | Book: … | Page: 64
    matched NOTHING, and every turn silently recorded `in_retrieved_context:
    False`. That is a phantom of exactly the `839a051` shape, and it survived the
    sanity case because THE FIXTURE WAS THE AUTHOR'S RECONSTRUCTION OF THE FORMAT
    RATHER THAN THE FORMAT (see _SANITY_REAL_CONTEXT). Parse by KEY, never by
    position, so an added header field cannot silently blind this again.
    """
    blocks = []
    if not retrieved_context:
        return blocks
    matches = list(_BLOCK_HEAD_RE.finditer(retrieved_context))
    for i, m in enumerate(matches):
        fields = {}
        for part in m.group(2).split("|"):
            if ":" not in part:
                continue
            k, _, v = part.partition(":")
            fields[k.strip().lower()] = v.strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(retrieved_context)
        head = retrieved_context[body_start:body_end].strip()
        page = fields.get("page")
        blocks.append({
            "index": int(m.group(1)),
            "chunk_id": fields.get("source"),
            "book_raw": fields.get("book"),
            "book": _book_key(fields.get("book")),
            "page": int(page) if page and page.isdigit() else None,
            "head": head[:240],
        })
    return blocks


def _resolve(book, page, blocks):
    """What lesson does (book, page) hold? Two INDEPENDENT resolvers, both keyed
    on the book (note 6). Never on the page alone."""
    ctx = next(
        (b for b in blocks if b["page"] == page and b["book"] == book), None
    )
    return {
        "library_skill_title": _LIBRARY.get((book, page)),
        "in_retrieved_context": ctx is not None,
        "context_chunk_id": ctx["chunk_id"] if ctx else None,
        "context_head": ctx["head"] if ctx else None,
    }


def _record(body, label, run, query, grade):
    resp = body.get("response")
    structured = resp if isinstance(resp, dict) else {}
    # The teacher-visible text. On the text path (both handlers here) it IS the
    # response; the structured branch is kept only so a surprise route is
    # recorded rather than silently read as "no citation" (note 2).
    if isinstance(resp, str):
        text = resp
    elif isinstance(resp, dict):
        text = "\n\n".join(f"{k}: {v}" for k, v in resp.items() if isinstance(v, str))
    else:
        text = ""

    blocks = _parse_retrieved_blocks(body.get("retrieved_context") or "")
    sites = _extract_sites(text)
    for s in sites:
        s["resolved"] = [
            _resolve(s["book"], p, blocks) for p in s["pages"]
        ] if s["book"] else []

    sources = body.get("sources") or []
    top = sources[0] if sources else {}
    cited_pages = [p for s in sites for p in s["pages"]]
    return {
        "label": label,
        "run": run,
        "query": query,
        "grade": grade,
        "intent": body.get("intent"),
        "response_kind": "structured" if isinstance(resp, dict) else "text",
        "quality": body.get("quality"),
        # --- the plan-(2) headline shape ---
        "n_citation_sites": len(sites),
        "n_pages_cited": len(cited_pages),
        "n_inline": sum(1 for s in sites if s["placement"] == "inline_with_claim"),
        "n_own_line": sum(1 for s in sites if s["placement"] == "own_line"),
        "n_fm5_template_sites": sum(1 for s in sites if s["is_fm5_template"]),
        "n_model_prose_sites": sum(1 for s in sites if not s["is_fm5_template"]),
        "citation_present": len(sites) > 0,
        "page_present": len(cited_pages) > 0,
        "cited_pages": cited_pages,
        "cited_books": sorted({s["book"] for s in sites if s["book"]}),
        "sites": sites,
        # --- context for the hand-read ---
        "n_lines": len(text.split("\n")),
        "response_text": text,
        "top_chunk_id": top.get("chunk_id"),
        "top_chunk_doc": top.get("source_document"),
        "top_chunk_book": _book_key(top.get("source_document")),
        "top_chunk_page": next(
            (b["page"] for b in blocks if b["chunk_id"] == top.get("chunk_id")), None
        ),
        "retrieved_blocks": blocks[:8],
        "sources": [
            {"chunk_id": s.get("chunk_id"), "source_document": s.get("source_document")}
            for s in sources[:6]
        ],
    }


# ---------------------------------------------------------------------------
# SANITY CASE (note 7) — proves the extractor can SEE what it is about to report
# missing. This probe's headline is an absence; an extractor that only knows our
# own footer would "confirm" that absence against any input whatsoever.
# ---------------------------------------------------------------------------

# Brady's image39, reconstructed from the spec §1.3 table. FIVE sites, SIX pages:
# a cited LEAD paragraph, two silent points, a two-page claim, and inline
# parentheticals throughout — every feature the live app is expected to lack.
_SANITY_IMAGE39 = """Grade 2 | Informative

Helping second graders write complete sentences starts with making the parts \
visible (Launching the Writers Workshop K-2, page 99).

1. Teach what makes a sentence complete
2. Clarify the difference between letters, words, and sentences (Launching the \
Writers Workshop K-2, page 96)
3. Strengthen sentence conventions through daily practice (Launching the Writers \
Workshop K-2, pages 97, 111)
4. Expand labels into full sentences (Launching the Writers Workshop K-2, page 99)
5. Fix incomplete writing with the Spider Legs strategy (Launching the Writers \
Workshop K-2, page 101)

Are you ready for a scripted mini-lesson on this skill?"""

# image11 — Brady's RED-praised COACHING close: book title, NO page.
_SANITY_IMAGE11 = """The organizer has three flaps that students lift as they draft.

For more details and to access any related resources, check the "Launching the \
Writers Workshop K-2" book and its digital resources — that's where the \
organizer lives."""

# What we ship today: ONE Fm5 footer on its own line, after the list.
_SANITY_OURS = """Grade 3 | Informative

Here is how I would approach it.

1. Model the table-top and leg strategy
2. Practice with a shared topic

If you have the 'Launching the Writers Workshop 3-12' book, you'll find this \
lesson on p.64.

Does this make sense?"""

_SANITY_NONE = """Grade 3 | Informative

1. Model the strategy
2. Practice together

Does this make sense?"""

# 🔴 CAPTURED VERBATIM OFF THE WIRE (POST /api/chat, "How do I teach paragraph
# writing to 3rd graders?", 2026-07-17), NOT reconstructed. This is the whole
# lesson of this probe's own near-miss: the first fixture here was written from
# the author's reading of `_format_chunk`'s Book/Page half and OMITTED the
# Type/Grade/Trait fields the real header carries. It passed, while the parser it
# was "proving" matched ZERO real blocks and silently reported every cited page
# as absent from its own context. A fixture you wrote from your belief about a
# format tests your belief, not the format.
#
# (Blocks 1 and 2 are Brady's OWN p.64 and p.124 — both retrieved on his
# paragraphing case, which is why "we cite only rank 1" is a shape question, not
# a retrieval one. Block 3 is spliced in from a K-2 turn to exercise the
# page-collision discrimination: p.64 exists in BOTH books.)
_SANITY_REAL_CONTEXT = """=== RETRIEVED CONTEXT ===

[1] Source: lww312-s8-ml05-table-top-leg-sentences | Type: textbook_lesson | \
Grade: 3-12 | Trait: Ideas | Book: Launching the Writers Workshop 3-12 | Page: 64
Launching the Writer's Workshop: Grades 3-12 — Section 8: Teaching Ideas
Mini-Lesson #5: Add "leg" sentences per "table-top" reason
[2] Source: lww312-s13-ml3-indent-new-information | Type: textbook_lesson | \
Grade: 3-12 | Trait: Conventions | Book: Launching the Writers Workshop 3-12 | Page: 124
Mini-Lesson #3: Indent for new information
[3] Source: k2-s8-ml8-draw-feelings-on-faces | Type: textbook_lesson | \
Grade: K-2 | Trait: Ideas | Book: Launching the Writers Workshop K-2 | Page: 64
Mini-Lesson #8: Draw feelings on faces
"""


def _sanity():
    """Returns (ok, [lines]). Every assertion is a thing this probe CLAIMS to be
    able to see. If any fails, its live numbers are not evidence."""
    log, ok = [], True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        log.append(f"  {'PASS' if good else 'FAIL'}  {name}: got {got!r}, want {want!r}")

    s39 = _extract_sites(_SANITY_IMAGE39)
    check("image39 citation sites", len(s39), 5)
    check("image39 pages", sum(x["n_pages"] for x in s39), 6)
    check("image39 two-page claim kept as ONE site",
          sorted(x["n_pages"] for x in s39), [1, 1, 1, 1, 2])
    check("image39 inline-with-claim sites", sum(1 for x in s39 if x["placement"] == "inline_with_claim"), 5)
    check("image39 own-line sites", sum(1 for x in s39 if x["placement"] == "own_line"), 0)
    # sorted() over a set that may hold None must not raise: a site with no book
    # is a real live possibility (a bare page mention is what a leak looks like),
    # and a crash here would read as a broken probe rather than a finding.
    check("image39 books all K-2", sorted(str(x["book"]) for x in s39), ["K-2"] * 5)
    check("image39 none are our Fm5 template", sum(1 for x in s39 if x["is_fm5_template"]), 0)
    # A cited LEAD paragraph is decision #2's whole subject; it must be visible.
    check("image39 lead paragraph is a cited site",
          any(x["line_index"] <= 2 and x["pages"] == [99] for x in s39), True)

    s11 = _extract_sites(_SANITY_IMAGE11)
    check("image11 sites (book, NO page)", len(s11), 1)
    check("image11 pages", sum(x["n_pages"] for x in s11), 0)
    check("image11 book", s11[0]["book"] if s11 else None, "K-2")

    ours = _extract_sites(_SANITY_OURS)
    check("our footer sites", len(ours), 1)
    check("our footer pages", sum(x["n_pages"] for x in ours), 1)
    check("our footer is own_line", ours[0]["placement"] if ours else None, "own_line")
    check("our footer is recognised as the Fm5 template",
          ours[0]["is_fm5_template"] if ours else None, True)
    check("our footer page", ours[0]["pages"] if ours else None, [64])

    check("uncited response -> 0 sites", len(_extract_sites(_SANITY_NONE)), 0)

    # Resolution is keyed on the BOOK, never the page alone (note 6) — the check
    # that would catch a K-2-at-grade-3 mis-cite being scored correct.
    check("p.64 resolves DIFFERENTLY per book",
          (_LIBRARY.get(("Teal", 64)), _LIBRARY.get(("K-2", 64))),
          ('Add "leg" sentences per "table-top" reason', "Draw feelings on faces"))
    check("p.124 resolves DIFFERENTLY per book",
          (_LIBRARY.get(("Teal", 124)), _LIBRARY.get(("K-2", 124))),
          ("Indent for new information", "Name the what (opinion) & why (reasons)"))

    blocks = _parse_retrieved_blocks(_SANITY_REAL_CONTEXT)
    check("context header parse -> 3 blocks", len(blocks), 3)
    check("context header parse -> books",
          [b["book"] for b in blocks], ["Teal", "Teal", "K-2"])
    check("context header parse -> pages", [b["page"] for b in blocks], [64, 124, 64])
    check("context header parse -> chunk ids",
          [b["chunk_id"] for b in blocks],
          ["lww312-s8-ml05-table-top-leg-sentences",
           "lww312-s13-ml3-indent-new-information",
           "k2-s8-ml8-draw-feelings-on-faces"])
    check("context header parse -> body captured", bool(blocks and blocks[0]["head"]), True)
    # The end-to-end path the phantom hid in: a cited (book, page) must resolve
    # against the context. This is the check whose ABSENCE let every turn record
    # in_retrieved_context=False.
    check("(Teal, 64) resolves IN CONTEXT", _resolve("Teal", 64, blocks)["in_retrieved_context"], True)
    check("(Teal, 124) resolves IN CONTEXT", _resolve("Teal", 124, blocks)["in_retrieved_context"], True)
    # …and the book must discriminate: K-2 p.124 is NOT in this context even
    # though Teal p.124 is. A page-keyed resolver would say True.
    check("(K-2, 124) correctly NOT in context",
          _resolve("K-2", 124, blocks)["in_retrieved_context"], False)
    check("(Teal, 999) correctly NOT in context",
          _resolve("Teal", 999, blocks)["in_retrieved_context"], False)
    return ok, log


async def _post(client, message, session_id, user_id=None):
    r = await client.post(
        f"{API}/api/chat",
        json={
            "message": message,
            "session_id": session_id,
            "user_id": user_id or f"probe-{uuid.uuid4()}",
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.json()


async def one(client, label, query, grade, i):
    body = await _post(client, query, f"perclaim-{label}-{i}".replace(" ", "-"))
    return _record(body, label, i, query, grade)


async def main():
    ok, log = _sanity()
    print("SANITY CASE — can this probe SEE a per-claim citation?")
    print("\n".join(log))
    if not ok:
        print("\n!! SANITY FAILED — the extractor cannot see what it claims to "
              "measure. Its 'no inline citations' would be unfalsifiable. "
              "ABORTING before the drive.")
        sys.exit(1)
    print("  -> extractor SEES 5 inline sites / 6 pages in Brady's shape, and a "
          "page-less book pointer. An absence it reports is evidence.\n")
    if "--sanity-only" in sys.argv:
        return

    out = []
    async with httpx.AsyncClient() as client:
        for label, query, grade in CASES:
            for i in range(RUNS):
                try:
                    out.append(await one(client, label, query, grade, i))
                except Exception as e:  # noqa: BLE001
                    out.append({"label": label, "run": i, "error": repr(e)})

    path = os.path.join(_HERE, "perclaim_before.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)

    good = [r for r in out if not r.get("error")]
    errors = [r for r in out if r.get("error")]
    print(f"{len(good)} turns recorded, {len(errors)} errors")
    if errors:
        print("!! a sub-second failure measures NOTHING — check the backend is "
              "up before recording anything")
    # LIVE GUARD ON THIS PROBE'S OWN RESOLVER (see _parse_retrieved_blocks).
    # select_citation_source / resolve_attribution BOTH require the cited page to
    # appear in the assembled context's "Page:" headers, so a cited page that
    # this probe cannot find in the context means the PROBE is broken (or a real
    # bug exists) — never "the citation is ungrounded". The phantom version of
    # this parser reported 0% in-context across 25 turns and said nothing.
    n_ctx_pages = sum(
        1 for r in good for s in r["sites"] for x in (s.get("resolved") or [])
        if x["in_retrieved_context"]
    )
    n_res = sum(1 for r in good for s in r["sites"] for _ in (s.get("resolved") or []))
    n_blocks = sum(len(r["retrieved_blocks"]) for r in good)
    print(f"\nRESOLVER SELF-CHECK: {n_blocks} context blocks parsed across {len(good)} turns; "
          f"cited pages found in their own context: {n_ctx_pages}/{n_res}")
    if n_blocks == 0 or (n_res and n_ctx_pages == 0):
        print("!! THE RESOLVER IS BLIND — every cited page reported absent from a "
              "context that structurally must contain it. Fix the parser before "
              "reading ANY number below.")

    by_label = {}
    for r in good:
        by_label.setdefault(r["label"], []).append(r)
    print(f"\n{'case':<26} {'intent':<14} {'sites':>6} {'pages':>6} {'inline':>7} {'own-line':>9}")
    for label, rs in by_label.items():
        intents = {r["intent"] for r in rs}
        print(f"{label:<26} {'/'.join(sorted(intents)):<14} "
              f"{sum(r['n_citation_sites'] for r in rs):>6} "
              f"{sum(r['n_pages_cited'] for r in rs):>6} "
              f"{sum(r['n_inline'] for r in rs):>7} "
              f"{sum(r['n_own_line'] for r in rs):>9}")
    print(f"\nwrote {path}")
    print("NOW READ IT BY HAND. Per turn: how many sites, where do they sit, and "
          "does each cited page belong to the claim it is attached to — resolved "
          "WITHIN THE CITED BOOK (pages collide). Do NOT auto-verdict.")


if __name__ == "__main__":
    asyncio.run(main())
