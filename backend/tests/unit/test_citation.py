from handlers.citation import (
    build_soft_citation,
    resolve_attribution,
)


class _Chunk:
    """Minimal stand-in for retrieval.search.RetrievedChunk (only the fields
    _full_book_title + the selector + resolve_attribution read)."""
    def __init__(self, book_name=None, source_document=None, page_number=None, chunk_id=""):
        self.book_name = book_name
        self.source_document = source_document
        self.page_number = page_number
        self.chunk_id = chunk_id


def test_build_soft_citation_full_form():
    assert build_soft_citation("Launching the Writers Workshop 3-12", 64) == (
        "If you have the 'Launching the Writers Workshop 3-12' book, "
        "you'll find this lesson on p.64."
    )


def test_build_soft_citation_silent_without_page():
    assert build_soft_citation("Launching the Writers Workshop 3-12", None) == ""


def test_build_soft_citation_silent_without_title():
    assert build_soft_citation(None, 64) == ""


def test_build_soft_citation_silent_with_empty_title():
    # Empty-string title is falsy → silent, same as a None title.
    assert build_soft_citation("", 64) == ""


# ---------------------------------------------------------------------------
# REMOVED (2026-07-17): the five `select_citation_source` tests.
#
# They were not re-pointed, because every gate they locked is ALREADY locked
# below, on the resolver that replaced the selector — re-pointing would have
# duplicated existing tests rather than preserved coverage:
#
#   * "non-Launch chunk -> None"        -> ..._named_chunk_is_not_a_launch_book
#   * "page not in context -> None"     -> ..._page_is_not_in_the_assembled_context
#   * "no Page: headers at all -> None" -> the same test (its ctx has none)
#   * "chunk with no page -> None"      -> ..._named_chunk_has_no_page
#
# What is NOT re-pointed is the selector's ONE remaining behaviour: "of two
# qualifying chunks, cite the FIRST (top-ranked) one". That is the defect, not
# a contract — the citation says "THIS lesson" while rank picked it before the
# lesson existed. Its inverse is asserted directly below, in
# test_resolve_attribution_picks_the_named_chunk_not_the_top_ranked_one.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# One page or many (spec §3.5)
# ---------------------------------------------------------------------------


def test_singular_page_output_is_byte_identical_to_the_shipped_template():
    # Brady-approved wording. If this changes, the demo copy changes.
    assert build_soft_citation("Launching the Writers Workshop 3-12", 64) == (
        "If you have the 'Launching the Writers Workshop 3-12' book, "
        "you'll find this lesson on p.64."
    )


def test_a_scalar_page_still_works_for_library_precheck():
    # retrieval/library_precheck.py:472 passes _entry_page(entry) — a scalar.
    assert "p.64." in build_soft_citation("Launching the Writers Workshop 3-12", 64)


def test_a_STRING_page_renders_as_ONE_page_not_as_its_characters():
    """A str is iterable, so testing the scalar branch with isinstance(pages,
    int) sends "64" down the PLURAL path and renders "pages 6, 4." — malformed,
    with no signal. Only data keeps that unreachable: ml_library.py:79 reads
    d.get("page_number") uncoerced into LibraryEntry, a dataclass whose
    Optional[int] is unenforced at runtime, and library_precheck.py:472 — the
    scalar caller — is the one path NOT gated by the set[int] page-in-context
    check that makes a stray string fail toward silence everywhere else. One
    "page_number": "64" in the library JSON is all it would take."""
    assert build_soft_citation("Launching the Writers Workshop 3-12", "64") == (
        "If you have the 'Launching the Writers Workshop 3-12' book, "
        "you'll find this lesson on p.64."
    )


def test_multiple_pages_render_in_bradys_own_plural_form():
    # image39 pt3, which he called "all great": "(… K-2, pages 97, 111)"
    assert build_soft_citation("Launching the Writers Workshop K-2", [97, 111]) == (
        "If you have the 'Launching the Writers Workshop K-2' book, "
        "you'll find this lesson on pages 97, 111."
    )


def test_one_page_in_a_list_renders_as_the_singular_template():
    assert build_soft_citation("Launching the Writers Workshop 3-12", [64]) == (
        "If you have the 'Launching the Writers Workshop 3-12' book, "
        "you'll find this lesson on p.64."
    )


def test_silent_without_a_page():
    assert build_soft_citation("Launching the Writers Workshop 3-12", None) == ""
    assert build_soft_citation("Launching the Writers Workshop 3-12", []) == ""


def test_silent_without_a_book_title():
    assert build_soft_citation(None, 64) == ""
    assert build_soft_citation("", 64) == ""


# ---------------------------------------------------------------------------
# resolve_attribution — the source the GENERATOR named, not the top-ranked one
# (spec §3.2)
# ---------------------------------------------------------------------------

_TEAL = "Launching the Writers Workshop 3-12.pdf"
_TEAL_TITLE = "Launching the Writers Workshop 3-12"


def _ctx(*pages):
    """Assembled-context stand-in carrying real "Page: N" headers — all that
    validation.citations._retrieved_pages reads (it regexes "Page: N" and
    ignores every other header token, so the Source: ids here are filler)."""
    return "\n".join(
        f"[{i}] Source: s{i} | Book: {_TEAL_TITLE} | Page: {p}\nbody"
        for i, p in enumerate(pages, 1)
    )


def test_resolve_attribution_picks_the_named_chunk_not_the_top_ranked_one():
    """THE POINT OF THE WHOLE SLICE: the top chunk is a retrieval ATTRACTOR
    (p.92 "Craft informative introductions" was cited for three unrelated
    queries). The generator names what it used, and that must win."""
    attractor = _Chunk(source_document=_TEAL, page_number=92,
                       chunk_id="lww312-s9-ml15-informative-introductions")
    real = _Chunk(source_document=_TEAL, page_number=74,
                  chunk_id="lww312-s8-ml15-stay-on-topic")
    # attractor is FIRST — rank would pick it; attribution must not. This is
    # the ONE test that distinguishes attribution from rank: any rank-based
    # implementation returns (title, 92) here.
    assert resolve_attribution(
        "lww312-s8-ml15-stay-on-topic", [attractor, real], _ctx(92, 74)
    ) == (_TEAL_TITLE, 74)


def test_resolve_attribution_silent_when_the_model_named_nothing():
    """Silence must be decided by the INPUT, not fall out of a failed lookup.
    A chunk carrying no id of its own MATCHES a falsy name (getattr's default
    is None, and "" == ""), so each falsy input is paired with exactly that
    chunk — deleting the `if not chunk_id` guard turns this red."""
    idless = _Chunk(source_document=_TEAL, page_number=64, chunk_id=None)
    empty_id = _Chunk(source_document=_TEAL, page_number=64, chunk_id="")
    assert resolve_attribution(None, [idless], _ctx(64)) is None
    assert resolve_attribution("", [empty_id], _ctx(64)) is None


def test_resolve_attribution_silent_on_a_fabricated_id():
    """A hallucinated id must never become a citation."""
    c = _Chunk(source_document=_TEAL, page_number=64, chunk_id="lww312-s8-ml05")
    assert resolve_attribution("does-not-exist", [c], _ctx(64)) is None


def test_resolve_attribution_silent_when_the_named_chunk_has_no_page():
    c = _Chunk(source_document=_TEAL, page_number=None, chunk_id="lww312-s8-ml05")
    assert resolve_attribution("lww312-s8-ml05", [c], _ctx(64)) is None


def test_resolve_attribution_silent_when_the_named_chunk_is_not_a_launch_book():
    """Every retrieved block carries "Source: <id>" — including episodes and
    course JSON, which carry no Book: header at all (_full_book_title returns
    None for them). The model can name one; a book we cannot title must not be
    invented. The page IS in context here, so the title is the only gate."""
    episode = _Chunk(source_document="02-ai-coaching-language.json", page_number=12,
                     chunk_id="ai-coaching-language-c3")
    assert resolve_attribution("ai-coaching-language-c3", [episode], _ctx(12)) is None


def test_resolve_attribution_never_falls_back_to_another_chunk():
    """Silence, not the next best thing. Falling back to rank IS the defect:
    an implementation that reaches for the top-ranked citeable chunk when the
    NAMED one cannot be cited returns (title, 64) here."""
    pageless = _Chunk(source_document=_TEAL, page_number=None, chunk_id="named-but-pageless")
    citeable = _Chunk(source_document=_TEAL, page_number=64, chunk_id="lww312-s8-ml05")
    assert resolve_attribution("named-but-pageless", [pageless, citeable], _ctx(64)) is None


def test_resolve_attribution_silent_when_the_page_is_not_in_the_assembled_context():
    """Retained from Fm5 (8f2c6ef made it strict): the page must match a real
    Page: header, so the citation agrees with validate_book_citation and
    survives scrub_unverifiable_citations."""
    c = _Chunk(source_document=_TEAL, page_number=64, chunk_id="lww312-s8-ml05")
    assert resolve_attribution("lww312-s8-ml05", [c], "no page headers here") is None


def test_resolve_attribution_silent_on_empty_chunks():
    assert resolve_attribution("anything", [], "") is None
    assert resolve_attribution("anything", None, "") is None
