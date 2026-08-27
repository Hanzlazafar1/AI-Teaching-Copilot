"""Deterministic safety-net coverage for the Brady Protected Set (offline, no network).

Pins current CORRECT behavior at the enforcement seam — the validators and the
assembled ML prompt's content. These are characterization tests (green-on-write);
a regression here fails the always-on gate. Fuzzy/semantic invariants (actual
2A/2B depth of generated text, Launch-first ordering) are covered by the live
golden-master in tests/acceptance. See implementation-strategy.md §1b.
"""
from generation.lesson import MiniLesson
from handlers import scripted_ml_prompt
from handlers.citation import build_soft_citation
from retrieval.assembler import _BOOK_FULL_TITLE, assemble_context
from retrieval.reranker import rerank
from tests.protected_invariants import cites_own_grade_band, header_correct, no_marker_survives
from tests.unit.test_reranker import _chunk  # reuse the RetrievedChunk builder
from canonicalizer import get_canonicalizer, ResolutionKind
from validation.policy import (
    STEP_3_REQUIRED_PHRASES,
    validate_no_forbidden_words,
    validate_response_ending,
    validate_step_3_phrases,
)


def _lesson(**over) -> MiniLesson:
    base = dict(
        skill_focus="topic sentences",
        grade_level="4",
        writing_mode="Inform",
        step_1_introduce="Today we learn to write clear topic sentences.",
        step_2a_tell="A topic sentence names the paragraph's main idea. " * 6,
        step_2b_show=(
            "Let me model this. I close my eyes and picture my paragraph. "
            "I wonder what my main idea is. I think it is that dogs are loyal. " * 4
        ),
        step_3_interact=(
            "Help me with the next one. Turn and talk with your partner. "
            "Back to me. This is some of what I heard from you: a strong topic "
            "sentence names the main idea clearly so readers know exactly what "
            "the paragraph will be about."
        ),
        step_4_close="Great work today. Now write your own topic sentence. Let's go be writers!",
    )
    base.update(over)
    return MiniLesson(**base)


def test_step3_smekens_phrases_locked():
    assert validate_step_3_phrases(_lesson()) == []  # all four present -> passes
    missing = _lesson(step_3_interact="Let's just talk it over and then move on.")
    assert validate_step_3_phrases(missing), "missing Smekens phrases should be flagged"


def test_forbidden_words_locked():
    assert validate_no_forbidden_words("Give students quiet writing time to try it.") == []
    assert validate_no_forbidden_words(
        "Let's discuss this fun activity together."
    ), "banned words (discuss/activity) should be flagged"


def test_per_type_endings_locked():
    assert validate_response_ending(
        "HOW_TO_TEACH", "...Are you ready for a scripted mini-lesson on this skill?"
    ) == []
    assert validate_response_ending(
        "PLAN_UNIT", "...Is this helpful? Would you like a general outline of this unit?"
    ) == []
    assert validate_response_ending(
        "MANAGEMENT",
        "...This was an overview. Which ONE area or SINGLE routine would you like to start with?",
    ) == []
    assert validate_response_ending(
        "HOW_TO_TEACH", "No closing question here at all."
    ), "a missing required ending should be flagged"


def test_ml_prompt_contains_depth_rules_and_all_smekens_phrases():
    p = scripted_ml_prompt._BASE_PROMPT.lower()
    assert "step 2a" in p and "step 2b" in p            # the deep-modeling steps exist
    assert "at least 2" in p and "at least 4" in p      # 2A >=2x / 2B >=4x depth rules
    for phrase in STEP_3_REQUIRED_PHRASES:
        assert phrase in p, f"ML prompt missing Smekens cue: {phrase!r}"


def test_reranker_launch_first_beats_higher_score():
    """Launch-books-first is CATEGORICAL: a lower-scoring Launch chunk must
    still rank above a higher-scoring non-Launch chunk (reranker tier logic)."""
    launch = _chunk(chunk_id="launch", book_name="Teal",
                    is_scripted_lesson=True, writing_mode="Inform", score=0.40)
    nonlaunch = _chunk(chunk_id="essential",
                       source_document="Essential 2 - Craft.pdf", score=0.90)
    ranked = rerank([nonlaunch, launch], query_type="SCRIPTED_ML",
                    user_grade="4", writing_mode="Inform", top_k=10)
    assert ranked[0].chunk_id == "launch", "Launch chunk must rank first despite lower base score"


def test_assembler_preserves_launch_first_order():
    """Locks Launch-first assembler ordering (F18)."""
    launch = _chunk(chunk_id="launch", book_name="Teal",
                    is_scripted_lesson=True, writing_mode="Inform", score=0.40)
    nonlaunch = _chunk(chunk_id="essential",
                       source_document="Essential 2 - Craft.pdf", score=0.90)
    ranked = rerank([nonlaunch, launch], query_type="SCRIPTED_ML",
                    user_grade="4", writing_mode="Inform", top_k=10)
    _, included = assemble_context(ranked)
    assert included[0].chunk_id == "launch"


def test_skill_canonicalization_stable_and_never_none():
    """Session memory relies on stable skill keys; canonicalize never returns None."""
    canon = get_canonicalizer()
    r = canon.resolve("topic sentence")
    assert r.kind is ResolutionKind.SKILL and r.canonical == "topic sentences"
    assert canon.canonicalize_skill("  Some NEW Skill ") == "some new skill"  # normalized fallback


def test_meta_technique_not_overwritten_as_skill():
    """'turn and talk' is a pedagogical technique: resolve() classifies it
    META_TECHNIQUE so the dispatcher won't clobber a locked skill (v3 Turn-5 guard)."""
    canon = get_canonicalizer()
    assert canon.is_meta_technique("turn and talk")
    assert canon.resolve("turn and talk").kind is ResolutionKind.META_TECHNIQUE


def test_header_correct_accepts_valid_shapes_rejects_malformed():
    """Fm4 header invariant (Protected-Set checker). The three valid header
    shapes are 'Grade X', 'Grade X | <Mode adjective>' and 'Grade X | Management'
    — read from a structured lesson's `header` field (SCRIPTED_ML) OR the first
    non-empty line of a text handler's response (the 5 markdown handlers, e.g.
    MANAGEMENT). Rejects the raw 'Grade: N | Mode: …' form and an empty/absent
    header. This is the deterministic logic behind the invariant that is wired
    into the live Protected Set at the wave-boundary re-baseline."""
    # Valid — structured lesson (SCRIPTED_ML): grade + writing-mode adjective
    assert header_correct({"response": {"header": "Grade 4 | Informative"}})[0]
    assert header_correct({"response": {"header": "Grade 8 | Persuasive"}})[0]
    # Valid — structured lesson: grade-only (writing mode unstated)
    assert header_correct({"response": {"header": "Grade 3"}})[0]
    # Valid — structured lesson: narrative label + a letter grade (K)
    assert header_correct({"response": {"header": "Grade K | Narrative"}})[0]
    # Valid — text handler (MANAGEMENT): header is the first non-empty line,
    # and MANAGEMENT uses the 'Management' label rather than a writing mode.
    assert header_correct({"response": "Grade 3 | Management\n\nSet up a Help Desk station..."})[0]
    # Valid — text handler with a leading blank line before the header
    assert header_correct({"response": "\nGrade 5 | Informative\n\nbody..."})[0]

    # Invalid — the raw 'Grade: N | Mode: X' form must be rejected
    assert not header_correct({"response": {"header": "Grade: 4 | Mode: Inform"}})[0]
    # Invalid — a label outside the four known writing/management words
    assert not header_correct({"response": {"header": "Grade 4 | Explanatory"}})[0]
    # Invalid — empty header string
    assert not header_correct({"response": {"header": ""}})[0]
    # Invalid — structured lesson with no header field at all
    assert not header_correct({"response": {}})[0]
    # Invalid — empty text response (no header line present)
    assert not header_correct({"response": ""})[0]
    # Invalid — text response whose first line is not a header
    assert not header_correct({"response": "Here is some advice about routines."})[0]


# ===========================================================================
# The two CITATION invariants (Protected-Set checkers).
#
# The pack was citation-blind until these: 11 invariant keys, none about the
# book or page a response points a teacher at. So "golden re-baselined, zero new
# regressions" was, on every citation change ever shipped, a claim no check
# could have contradicted.
#
# Each test below is a MUTATION: it feeds the checker a deliberately broken
# response and asserts the checker FAILS, then feeds a correct one and asserts
# it passes. An invariant only ever asserted in the passing direction is a
# decoration — it is how a check that can never fail gets shipped as a gate.
#
# The citation fixtures are built by the REAL emitter (build_soft_citation over
# the real _BOOK_FULL_TITLE), never hand-written. A hand-written citation is a
# RECONSTRUCTION of the app's output: if the title map and the title regexes in
# validation/citations.py ever drift apart, the checker stops seeing real
# citations and goes vacuous, while a reconstruction-fed test stays green and
# certifies the vacuity. Sourcing both ends from the real code makes that drift
# fail HERE instead.
# ===========================================================================

_K2_CITATION = build_soft_citation(_BOOK_FULL_TITLE["K-2"], 113)
_TEAL_CITATION = build_soft_citation(_BOOK_FULL_TITLE["Teal"], 64)


def _ml(**over) -> dict:
    """A delivered SCRIPTED_ML payload — the `structured` dict routes_v4 ships."""
    base = {
        "skill_focus": "Topic sentences",
        "grade_level": "4",
        "header": "Grade 4",
        "step_1_introduce": "Today we learn topic sentences.",
        "step_2a_tell": "A topic sentence names the main idea.",
        "step_2b_show": "Let me model this. I picture my paragraph.",
        "step_3_interact": "Help me with the next one. Turn and talk.",
        "step_4_close": "Now it's your turn!",
        "book_citation": _TEAL_CITATION,
        "followup": "Does this script seem appropriate for your student-writers?",
    }
    base.update(over)
    return {"response": base}


def test_no_marker_survives_fails_on_a_raw_marker_and_passes_when_clean():
    """Kills: a checker that never looks, or looks only at the lesson steps."""
    assert no_marker_survives({"response": "A claim about leads. [[src:lww312-s8-ml05]]"})[0] is False
    assert no_marker_survives({"response": "A claim about leads."})[0] is True


def test_no_marker_survives_sees_the_REAL_scrubber_mangled_shape():
    """The shape that actually escapes, composed by the REAL pipeline rather
    than hand-written.

    scrub_unverifiable_citations runs BEFORE the resolver (mandatory order, per
    _base_text._build_text_outcome) and its _PAGE_SCRUB_RE rewrites `page-01`
    INSIDE a chunk id to a SPACE — outside citation.py::_MARKER_RE's pinned id
    class. 11 of 710 corpus ids are affected. A checker built from that grammar
    would miss exactly these and certify a marker shipped to a teacher.

    Kills: an audit pattern derived from _MARKER_RE.
    """
    from validation.citations import scrub_unverifiable_citations

    real_id = "ccss-page-01-college-and-career-readiness-anchor-standards-for-"
    mangled, _ = scrub_unverifiable_citations(f"A claim. [[src:{real_id}]] End.", "")
    # The premise, asserted as an OBSERVATION so a scrubber change surfaces here
    # with instructions rather than silently voiding the test.
    assert f"[[src:{real_id}]]" not in mangled, (
        "PREMISE CHANGED: the scrubber no longer mangles this id. Re-check "
        "whether the audit prefix still needs to be wider than _MARKER_RE."
    )
    assert no_marker_survives({"response": mangled})[0] is False


def test_no_marker_survives_is_WIDER_than_the_sweep_it_audits():
    """A marker with no closing `]]` escapes citation.py::_MARKER_SWEEP_RE — it
    requires the close, on the same line, within 200 chars. The audit must still
    catch it, or it could only ever confirm the sweep against itself.

    Kills: `no_marker_survives` implemented as `_MARKER_SWEEP_RE.search(...)`,
    which is a tautology — the sweep removes precisely what the sweep matches,
    so such a check passes by construction on every response the sweep touched.
    """
    from handlers.citation import _MARKER_SWEEP_RE

    escaped = "A claim. [[src:" + "x" * 400 + "]] End."
    assert not _MARKER_SWEEP_RE.search(escaped), "premise: this shape escapes the sweep"
    assert no_marker_survives({"response": escaped})[0] is False


def test_no_marker_survives_reads_fields_the_step_join_CANNOT_see():
    """`_text` joins the five STEP fields only, so it cannot see `book_citation`
    — the field the Fm5 footer actually ships in, and the one field on a
    SCRIPTED_ML payload that carries a citation at all.

    Kills: both citation checkers implemented on `_text`, which would pass
    vacuously on all 9 SCRIPTED_ML cases in the pack — the unfailable check
    these invariants exist to end.
    """
    assert no_marker_survives(_ml(book_citation="[[src:lww312-s8-ml05]]"))[0] is False
    assert no_marker_survives(_ml(followup="Want more? [[src:k2-a]]"))[0] is False
    assert no_marker_survives(_ml())[0] is True  # the same payload, unmutated, passes


def test_cites_own_grade_band_fails_when_a_grade3_answer_cites_the_K2_book():
    """Brady's own case. Pages COLLIDE across the two books — Teal p.64 is "Add
    'leg' sentences per 'table-top' reason", K-2 p.64 is "Draw feelings on
    faces" — so a page without its book sends a teacher to a real page of the
    wrong book, confidently and with no signal.

    Kills: a checker that only looks at the page, or only at whether SOME book
    was cited.
    """
    g3_wrong = f"Grade 3\n\nParagraphing takes modeling. {_K2_CITATION}"
    ok, detail = cites_own_grade_band({"response": g3_wrong})
    assert ok is False
    assert "K-2" in detail and "wrong band" in detail

    g3_right = f"Grade 3\n\nParagraphing takes modeling. {_TEAL_CITATION}"
    assert cites_own_grade_band({"response": g3_right})[0] is True


def test_cites_own_grade_band_bands_K_and_the_low_grades_to_the_K2_book():
    """The invariant is symmetric: the 3-12 book is just as wrong for Grade K as
    the K-2 book is for Grade 3. Kills: a checker hardcoded to one direction."""
    assert cites_own_grade_band({"response": f"Grade K | Narrative\n\n{_K2_CITATION}"})[0] is True
    assert cites_own_grade_band({"response": f"Grade K | Narrative\n\n{_TEAL_CITATION}"})[0] is False
    assert cites_own_grade_band({"response": f"Grade 2\n\n{_K2_CITATION}"})[0] is True
    assert cites_own_grade_band({"response": f"Grade 2\n\n{_TEAL_CITATION}"})[0] is False


def test_cites_own_grade_band_sees_the_structured_book_citation_field():
    """The SCRIPTED_ML footer lives on `structured["book_citation"]`, which
    routes_v4 ships while DISCARDING response_text. A checker reading the step
    fields sees none of it.

    Kills: the `_text`-based implementation — vacuously green on every
    SCRIPTED_ML case in the pack.
    """
    assert cites_own_grade_band(_ml(header="Grade 4", book_citation=_K2_CITATION))[0] is False
    assert cites_own_grade_band(_ml(header="Grade 4", book_citation=_TEAL_CITATION))[0] is True
    assert cites_own_grade_band(_ml(header="Grade 1", book_citation=_K2_CITATION))[0] is True


def test_cites_own_grade_band_FAILS_rather_than_shrugs_when_it_cannot_band():
    """A cited book we cannot band is a citation we cannot check, and "cannot
    check" must read as a failure. Passing here is how an invariant quietly
    becomes a decoration — the shape this whole task exists to remove.

    Kills: `if not grade: return True`.
    """
    ok, detail = cites_own_grade_band({"response": f"No header here. {_K2_CITATION}"})
    assert ok is False
    assert "cannot be verified" in detail


def test_cites_own_grade_band_passes_when_nothing_is_cited():
    """Genuinely conditional, not vacuous: silence is Brady's stated preference
    over a wrong pointer, so an uncited response has nothing to contradict. The
    tests above are what prove the checker still bites when a citation IS
    present."""
    assert cites_own_grade_band({"response": "Grade 3\n\nParagraphing takes modeling."})[0] is True
    assert cites_own_grade_band(_ml(book_citation=""))[0] is True


def test_both_citation_invariants_are_wired_into_the_pack():
    """The checkers above are worth nothing until the pack opts cases in — the
    Fm3/S3 class of defect (a correct rule wired to nothing that reaches the
    teacher). `no_marker_survives` is unconditional; `cites_own_grade_band`
    covers every case whose ask names a grade."""
    from tests.protected_set import PROTECTED_SET

    assert all("no_marker_survives" in c.invariants for c in PROTECTED_SET)
    banded = {c.id for c in PROTECTED_SET if "cites_own_grade_band" in c.invariants}
    assert len(banded) == 12, f"expected the 12 grade-stating cases, got {sorted(banded)}"
    # The four that state no grade carry no band invariant — there is no header
    # to band them against. Named so removing a grade from a case's ask cannot
    # silently drop its citation coverage.
    assert {c.id for c in PROTECTED_SET} - banded == {
        "coaching_wont_start", "management_routines",
        "pizza_table_named", "think_aloud_topic_sentences",
    }
