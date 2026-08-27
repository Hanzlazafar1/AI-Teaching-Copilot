"""The marker resolver: the model points, the code speaks — in markdown.

Each test names the mutation it kills. A test that passes against a broken
implementation is worse than no test (six such shipped in plan (1)'s briefs).

Helpers are IMPORTED from test_citation.py rather than re-declared: two
independent _Chunk stand-ins would drift apart from RetrievedChunk
independently, which is the same defect class the PAGE_TOKEN grammar comment
in validation/citations.py describes. _ctx builds real "Page: N" headers and
nothing else is read from it (its Book:/Source: tokens are documented filler),
so a K-2 chunk under a _ctx built with the 3-12 title is not a mismatch — the
title always comes from the CHUNK.
"""
from handlers.citation import resolve_markers
from handlers.picklist import extract_offered_skills
from tests.unit.test_citation import _Chunk, _ctx, _TEAL, _TEAL_TITLE


def test_a_resolved_marker_becomes_bradys_sentence_IN_PLACE():
    """Kills: appending the citation as a footer instead of resolving in place."""
    c = _Chunk(source_document=_TEAL, page_number=64, chunk_id="lww312-s8-ml05")
    text = "- **Introduce the strategy**: a paragraph is like a table. [[src:lww312-s8-ml05]]\n- **Next point**: something else."
    out = resolve_markers(text, [c], _ctx(64))
    first_line = out.splitlines()[0]
    assert "you'll find this lesson on p.64." in first_line   # SAME line as its claim
    assert "[[src:" not in out


def test_an_unresolvable_marker_is_STRIPPED_not_left():
    """Kills: leaving an unresolved marker in teacher-visible text."""
    c = _Chunk(source_document=_TEAL, page_number=64, chunk_id="lww312-s8-ml05")
    out = resolve_markers("A claim. [[src:does-not-exist]] Another.", [c], _ctx(64))
    assert "[[src:" not in out
    assert "does-not-exist" not in out
    assert "p.64" not in out            # and it must NOT fall back to another chunk


def test_a_SCRUBBER_MANGLED_marker_is_still_swept():
    """MEASURED, not hypothetical: _PAGE_SCRUB_RE turns
    [[src:ccss-page-01-...]] into [[src:ccss- -...]] — a SPACE the pinned
    grammar does not admit. 11 of 710 corpus ids are affected.
    Kills: a sweep that reuses the marker grammar."""
    out = resolve_markers("A claim. [[src:ccss- -college-and-career-readiness]] End.", [], "")
    assert "[[src:" not in out


def test_the_REAL_scrubbers_output_is_swept_not_a_RECONSTRUCTION_of_it():
    """The test above hand-writes "[[src:ccss- -college...]]" — that string is a
    RECONSTRUCTION of the scrubber's output, not the output. If _PAGE_SCRUB_RE's
    mangling ever changes shape, that test keeps passing while the real pipeline
    ships a marker to a teacher. (A sanity fixture that reconstructs the format
    instead of using it is one of the unfailable-check shapes this campaign has
    already paid for.)

    So compose the REAL pipeline in its REAL order: scrub_unverifiable_citations
    runs BEFORE this resolver — mandatory, per _base_text._build_text_outcome,
    which enforces that order and documents why — and IS what mangles the id.
    Kills: a sweep tuned to a reconstruction.
    """
    from validation.citations import scrub_unverifiable_citations

    real_id = "ccss-page-01-college-and-career-readiness-anchor-standards-for-"
    scrubbed, _ = scrub_unverifiable_citations(
        f"A claim about standards. [[src:{real_id}]] End.", ""
    )
    # The premise, stated as an OBSERVATION so a scrubber change surfaces here
    # with instructions rather than silently voiding the test above.
    assert f"[[src:{real_id}]]" not in scrubbed, (
        "PREMISE CHANGED: the scrubber no longer mangles this chunk id. "
        "Re-check whether _MARKER_SWEEP_RE still needs to be wider than "
        "_MARKER_RE before relaxing it."
    )
    # The invariant, unconditional: no marker is ever teacher-visible.
    assert "[[src:" not in resolve_markers(scrubbed, [], "")


def test_multiple_markers_on_one_claim_join_into_ONE_sentence():
    """Brady's image39 point 3 cites 'pages 97, 111' on a single claim and he
    called that response 'all great'. Kills: repeating the book title per page."""
    a = _Chunk(source_document="Launching the Writers Workshop K-2.pdf", page_number=97, chunk_id="k2-a")
    b = _Chunk(source_document="Launching the Writers Workshop K-2.pdf", page_number=111, chunk_id="k2-b")
    out = resolve_markers("A claim. [[src:k2-a]] [[src:k2-b]]", [a, b], _ctx(97, 111))
    assert out.count("If you have the") == 1
    assert "pages 97, 111." in out


def test_markers_on_DIFFERENT_claims_each_get_their_own_sentence():
    """Brady: 'here, and down here'. Kills: collapsing to one citation."""
    a = _Chunk(source_document=_TEAL, page_number=64, chunk_id="a1")
    b = _Chunk(source_document=_TEAL, page_number=124, chunk_id="b1")
    out = resolve_markers("- Point one. [[src:a1]]\n- Point two. [[src:b1]]", [a, b], _ctx(64, 124))
    assert out.count("If you have the") == 2
    assert "p.64." in out.splitlines()[0] and "p.124." in out.splitlines()[1]


def test_text_with_no_markers_is_returned_UNCHANGED():
    """Kills: a resolver that mangles the 3 handlers that must stay uncited.
    MANAGEMENT / PLAN_UNIT / THINK_ALOUD never emit a marker, yet this resolver
    runs over their delivered text — so "changes nothing" has to be provable,
    not merely intended.

    FIXTURE WARNING — every oddity below is load-bearing; do not "tidy" it. The
    trailing spaces, the interior double space and the trailing newline are
    exactly the shapes _tidy_after_removal rewrites, and an LLM emits all three
    routinely. The brief's original fixture ("A plain answer.\\n\\nDoes this make
    sense?") was clean prose, invariant under the tidier — so it passed even
    with the byte-identical guard DELETED. Proven by mutation, not argued: it
    could not fail. A fixture that cannot reach the code it guards is not a test.
    """
    text = (
        "Grade 3 | Management\n\n"
        "Here is the routine:  \n"             # trailing spaces
        "1. **Model it.** Show them  how.\n"   # interior double space
        "    - a nested note\n"                # leading indent (markdown nesting)
        "\n"
        "Does this make sense?\n"              # trailing newline
    )
    assert resolve_markers(text, [], "") == text


# ---------------------------------------------------------------------------
# The invariants the six above only cover by PROXY.
# ---------------------------------------------------------------------------


def test_the_PICK_LIST_survives_resolution():
    """THE nn4 REGRESSION LOCK — the reason resolution is per-line.

    The tests above assert "the citation lands on the claim's line", which is a
    PROXY for the thing that actually matters: picklist._scan_list_lines is
    `elif in_list: break` ("prose after the list does end it"), and
    _base_text.py:596 records offered_skills off the text a citation has already
    entered. So a citation on its OWN line mid-list TRUNCATES the pick-list,
    "number 4" goes out of range, and yesterday's nn4 fix silently reverts —
    the campaign's worst-defect class (a teacher asks for 4 and is handed 3,
    confidently, with no signal).

    This drives the real extractor instead of trusting the proxy. Kills: any
    footer/own-line placement (the list truncates to 1 item), and any placement
    that corrupts the skill NAME (_lead_sentence would swallow the citation).
    """
    chunks = [
        _Chunk(source_document=_TEAL, page_number=64, chunk_id=f"c{i}")
        for i in range(1, 5)
    ]
    text = "\n".join(
        f"{i}. **Skill {i} sentence.** Why it matters. [[src:c{i}]]"
        for i in range(1, 5)
    )
    out = resolve_markers(text, chunks, _ctx(64))

    skills = extract_offered_skills(out)
    assert len(skills) == 4, f"pick-list truncated to {len(skills)}: {skills}"
    assert skills[3] == "Skill 4 sentence"   # "number 4" still resolves to 4
    assert "If you have the" not in skills[3]  # the citation is not the name


def test_two_DIFFERENT_books_on_one_claim_each_get_their_own_sentence():
    """Kills: grouping by line instead of by BOOK — which would render one
    sentence naming one title while carrying the other book's page, i.e. cite
    a page that does not exist in the book named. The join in
    test_multiple_markers_on_one_claim is keyed on the title, not the line."""
    a = _Chunk(source_document=_TEAL, page_number=64, chunk_id="teal-a")
    b = _Chunk(source_document="Launching the Writers Workshop K-2.pdf",
               page_number=97, chunk_id="k2-b")
    out = resolve_markers("One claim, two books. [[src:teal-a]] [[src:k2-b]]",
                          [a, b], _ctx(64, 97))
    assert out.count("If you have the") == 2
    assert f"'{_TEAL_TITLE}' book, you'll find this lesson on p.64." in out
    assert "'Launching the Writers Workshop K-2' book, you'll find this lesson on p.97." in out


def test_the_SAME_location_named_twice_renders_ONE_page_not_pages_15_15():
    """MEASURED: 31 of 225 Launch (book,page) locations hold MORE THAN ONE
    chunk, so two legitimately different markers on one claim can resolve to
    the same page — e.g. lww312-s1-ml4-abc-chart-topics and
    lww312-s1-ml5-springboard-off-texts are both p.15.

    A citation names a LOCATION in a physical book; the same location named
    twice is one location, not two. Selecting it twice would ship
    "on pages 15, 15." to a teacher. That de-duplication belongs HERE, in the
    selector that assembles the list — never in build_soft_citation, which is
    a pure formatter and must not rewrite its input (doing so would hide
    exactly this bug rather than surface it).

    Kills: passing the raw per-marker page list straight to the formatter.
    ORDER is still never touched — see the sibling test below.
    """
    a = _Chunk(source_document=_TEAL, page_number=15, chunk_id="lww312-s1-ml4-abc-chart-topics")
    b = _Chunk(source_document=_TEAL, page_number=15, chunk_id="lww312-s1-ml5-springboard-off-texts")
    # The claim NAMES both lessons (ABC chart topics / springboard off texts) so
    # the identity gate corroborates each descriptive chunk — a contentless "A
    # claim." now (correctly) resolves to silence against an identity-bearing
    # chunk, which would make this de-dup assertion vacuous.
    out = resolve_markers(
        "Kick topics off with the ABC chart topics lesson or springboard off texts. "
        "[[src:lww312-s1-ml4-abc-chart-topics]] [[src:lww312-s1-ml5-springboard-off-texts]]",
        [a, b], _ctx(15),
    )
    assert "pages 15, 15" not in out
    assert "you'll find this lesson on p.15." in out
    assert out.count("If you have the") == 1


def test_page_list_is_sorted_ascending():
    """CONTRACT CHANGE (recert fix (2c)): a multi-page citation now reads
    ASCENDING. A citation names locations in a PHYSICAL book, which a teacher
    flips front-to-back, so ascending is the order that helps — and it matches
    Brady's own approved 'pages 97, 111'. This SUPERSEDES the earlier
    'model's order, never sorted' rule, which carried no meaning a teacher could
    use and left the same two lessons rendering '124, 64' or '64, 124' at the
    mercy of generation nondeterminism. The sort lives in the list ASSEMBLER
    (``_resolve_one_line``); ``build_soft_citation`` stays a pure formatter that
    renders whatever order its caller hands it.

    Kills: assembling the pages in the model's pointer order."""
    # Structurally-bare ids (all-digit fragments) carry no lesson identity, so
    # the new identity gate does not enter and this test isolates page ORDER.
    a = _Chunk(source_document=_TEAL, page_number=124, chunk_id="lww312-s8-ml05")
    b = _Chunk(source_document=_TEAL, page_number=64, chunk_id="lww312-s8-ml06")
    out = resolve_markers(
        "A claim. [[src:lww312-s8-ml05]] [[src:lww312-s8-ml06]]", [a, b], _ctx(124, 64)
    )
    assert "pages 64, 124." in out
