"""The claim<->chunk IDENTITY gate + cross-line hygiene (recert fix (1)+(2)).

THE BUG this locks (proven + deterministically reproduced on ``recert-P09``):
``resolve_attribution`` used to accept a ``[[src:<id>]]`` marker on PROVENANCE
("the chunk's page is in this turn's retrieved set") but never on IDENTITY ("is
this chunk the lesson the CLAIM is about?"). On a bare follow-up ("4th grade")
retrieval DRIFTS — the real lesson chunk is absent — the model describes the
lesson from memory and marks the nearest retrieved DECOY, so a confident WRONG
page ships. The gate below requires the marked chunk to be corroborated as the
lesson the claim names, routed through the ``skill_triggers`` synonym map so a
teacher's "pizza table" still matches the chunk slug ``table-top-leg-sentences``.

Fail direction is SILENCE (Brady: "better to stay silent than lie") — the same
direction as the existing empty-chunks / page-not-in-context gates.

THE RISK is OVER-SUPPRESSION of correct cites, so the gate is deliberately
narrow: it suppresses ONLY when the chunk carries a determinable lesson identity
that the claim fails to mention. A chunk whose id carries no distinctive tokens
(the ``lww312-s8-ml05`` test shorthand; no real corpus id is this bare) is
indeterminate -> the gate cannot prove a mismatch -> it does NOT suppress. That
is what keeps the perclaim-wiring / fm5 / location-lookup end-to-end fixtures —
all of which mark that bare id — citing exactly as before.

Each test names the mutation it kills; a test that passes against a broken
implementation is worse than none (the house rule this module inherits).
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from handlers.citation import resolve_attribution, resolve_markers
from tests.unit.test_citation import _Chunk, _TEAL, _TEAL_TITLE, _ctx


def _chunk(chunk_id, page, *, lesson_trigger=None, skill_title="", source_document=_TEAL):
    """A RetrievedChunk stand-in carrying the identity fields the gate reads
    (``chunk_id`` slug, ``lesson_trigger`` tags, ``skill_title``) on top of the
    provenance fields ``_Chunk`` already models."""
    c = _Chunk(source_document=source_document, page_number=page, chunk_id=chunk_id)
    c.lesson_trigger = list(lesson_trigger or [])
    c.skill_title = skill_title
    c.strategy_name = ""
    return c


_PIZZA_ID = "lww312-s8-ml05-table-top-leg-sentences"   # the real pizza-table lesson, p.64
_RUBRIC_ID = "lww312-s7-one-rubric-all-writing-units"   # the P09 turn-1 DECOY, p.57


# ---------------------------------------------------------------------------
# (1) The identity gate — cite the right lesson, stay silent on the wrong one
# ---------------------------------------------------------------------------


def test_1_pizza_claim_marking_the_real_table_top_chunk_cites_p64():
    """Kills: a gate that suppresses a corroborated cite (over-suppression) —
    the claim names the pizza-table / table-top strategy and the marked chunk
    IS that lesson, so it must cite p.64."""
    c = _chunk(_PIZZA_ID, 64)
    claim = "Use the pizza-table / table-top strategy to build a paragraph."
    assert resolve_attribution(_PIZZA_ID, [c], _ctx(64), claim_text=claim) == (_TEAL_TITLE, 64)
    out = resolve_markers(f"{claim} [[src:{_PIZZA_ID}]]", [c], _ctx(64))
    assert "you'll find this lesson on p.64." in out
    assert "[[src:" not in out


def test_2_same_pizza_claim_marking_the_wrong_lesson_chunk_is_silent():
    """THE BUG. Same pizza claim, but the marked chunk is the DRIFTED decoy
    (an overview about one rubric for all writing units, p.57). Its page IS in
    context, so the OLD provenance-only gate cited p.57. Identity says the decoy
    is not the pizza lesson -> silence.

    Kills: the provenance-only gate (returns (title, 57) here); and a gate that
    reads the marker text itself as the claim (the id ``one-rubric...`` would
    then 'corroborate' itself)."""
    decoy = _chunk(_RUBRIC_ID, 57)
    claim = "Use the pizza-table / table-top strategy to build a paragraph."
    assert resolve_attribution(_RUBRIC_ID, [decoy], _ctx(57), claim_text=claim) is None
    out = resolve_markers(f"{claim} [[src:{_RUBRIC_ID}]]", [decoy], _ctx(57))
    assert "you'll find this lesson" not in out
    assert "p.57" not in out
    assert "[[src:" not in out            # the marker is still SWEPT, never leaked


def test_3_synonym_teacher_wording_still_matches_the_chunk_slug():
    """The teacher's word ("pizza table") differs from the chunk slug
    ("table-top-leg-sentences"); the synonym map bridges them. Kills: an
    identity check that compares raw strings without the trigger map."""
    c = _chunk(_PIZZA_ID, 64)
    out = resolve_markers(
        f"Yes — the pizza table lesson is what you want. [[src:{_PIZZA_ID}]]",
        [c], _ctx(64),
    )
    assert "you'll find this lesson on p.64." in out


def test_3b_trigger_TAG_and_synonym_bridge_an_opaque_slug():
    """Isolates the synonym-map path from raw-token overlap. The claim uses the
    pure synonym 'tables and legs'; the chunk slug ('elaboration-frame') shares
    NO word with it, and the ONLY bridge is the pizza-table ``lesson_trigger``
    tag + the synonym map. Kills: dropping the tag from identity, or matching
    triggers only by exact name (not synonym)."""
    c = _chunk("lww312-s8-ml05-elaboration-frame", 64, lesson_trigger=["pizza-table"])
    assert resolve_attribution(
        c.chunk_id, [c], _ctx(64), claim_text="Use the tables-and-legs trick."
    ) == (_TEAL_TITLE, 64)


def test_overview_chunk_type_is_never_cited_as_this_lesson():
    """recert-P09 turn 1 (LIVE, after the id gate shipped): retrieval drifted,
    the pizza chunk was absent, and the model marked ``lww312-overview-how-to-use``
    (p.4) / pacing (p.5) OVERVIEW pages. Their all-stopword slugs are identity-
    INDETERMINATE, so the token gate fell through to CITING — a wrong 'this lesson
    on p.4'. A book overview / pacing / rubric page is never 'this lesson':
    suppress the ``textbook_overview`` content_type. Kills: the indeterminate-
    overview -> cite leak."""
    ov = _chunk("lww312-overview-how-to-use", 4)
    ov.content_type = "textbook_overview"
    claim = "Use the pizza-table / table-top strategy to build a paragraph."
    assert resolve_attribution(ov.chunk_id, [ov], _ctx(4), claim_text=claim) is None
    out = resolve_markers(f"{claim} [[src:{ov.chunk_id}]]", [ov], _ctx(4))
    assert "you'll find this lesson" not in out
    assert "p.4" not in out
    assert "[[src:" not in out            # marker still swept, never leaked


def test_lesson_type_chunk_still_cited_type_gate_does_not_oversuppress():
    """The type gate touches ONLY non-lesson types. A real lesson chunk
    (``textbook_lesson``) that corroborates the claim still cites — the type
    gate must not silence lessons. Kills: a type gate applied to every chunk."""
    c = _chunk(_PIZZA_ID, 64)
    c.content_type = "textbook_lesson"
    assert resolve_attribution(
        c.chunk_id, [c], _ctx(64),
        claim_text="Use the pizza-table / table-top strategy.",
    ) == (_TEAL_TITLE, 64)


def test_indeterminate_chunk_id_is_NOT_suppressed():
    """A chunk whose id carries no distinctive tokens (the bare test shorthand;
    no real corpus id is this bare) is identity-indeterminate — the gate cannot
    prove a mismatch, so it must NOT suppress. This is what keeps the
    perclaim-wiring / fm5 fixtures green. Kills: a gate that silences whenever
    the claim happens not to overlap the id."""
    c = _chunk("lww312-s8-ml05", 64)
    out = resolve_markers(
        "Model connectors like 'however' between paragraphs. [[src:lww312-s8-ml05]]",
        [c], _ctx(64),
    )
    assert "you'll find this lesson on p.64." in out


def test_claim_text_absent_skips_the_gate_scripted_ml_path():
    """SCRIPTED_ML resolves ``MiniLesson.source_chunk_id`` with NO claim text
    (``handlers/scripted_ml.py`` calls the 3-arg form). The gate must be OFF
    there — the whole lesson IS the claim, and there is no per-line text to
    corroborate. Kills: making the identity gate mandatory (which would silence
    every SCRIPTED_ML citation, since a mismatched-looking descriptive claim is
    not available)."""
    decoy = _chunk(_RUBRIC_ID, 57)
    # A pizza-ish caller with NO claim_text still resolves the marked chunk —
    # the 3-arg contract is preserved byte-for-byte.
    assert resolve_attribution(_RUBRIC_ID, [decoy], _ctx(57)) == (_TEAL_TITLE, 57)


def test_7_two_different_corroborated_lessons_BOTH_survive():
    """THE OVER-SUPPRESSION GUARD (the stated risk). A legit multi-lesson
    coaching reply names two DIFFERENT real lessons, each on its own claim line,
    each corroborated by its own chunk. BOTH must cite. Kills: a gate so strict
    it silences correct cites, and any global (rather than per-claim) matching."""
    pizza = _chunk(_PIZZA_ID, 64)
    snapple = _chunk("lww312-s8-ml07-snapple-details", 66)
    out = resolve_markers(
        "For elaboration, use the table-top / leg sentences lesson. "
        f"[[src:{_PIZZA_ID}]]\n"
        "For specificity, use the Snapple details lesson. "
        "[[src:lww312-s8-ml07-snapple-details]]",
        [pizza, snapple], _ctx(64, 66),
    )
    assert "you'll find this lesson on p.64." in out
    assert "you'll find this lesson on p.66." in out


# ---------------------------------------------------------------------------
# (2) Hygiene — dedup / colon+question suppression / ascending pages
# ---------------------------------------------------------------------------


def test_4_identical_footer_on_two_lines_is_emitted_ONCE():
    """(2a) Same chunk marked on two lines -> one citation, not a repeated
    footer. Kills: per-line resolution with no cross-line reconciliation."""
    c = _chunk("lww312-s8-ml05", 64)   # indeterminate id -> always cites
    out = resolve_markers(
        "Step 1. Model it. [[src:lww312-s8-ml05]]\n"
        "Step 2. Guide it. [[src:lww312-s8-ml05]]",
        [c], _ctx(64),
    )
    assert out.count("you'll find this lesson on p.64.") == 1


def test_5_marker_on_a_colon_lead_in_line_gets_NO_citation():
    """(2b) A ':' is a list lead-in; a citation jammed after it reads as noise
    and (worse) can truncate a downstream pick-list. Suppress the marker, keep
    the lead-in. Kills: appending a sentence after the colon."""
    c = _chunk("lww312-s8-ml05", 64)
    out = resolve_markers(
        "Here are the focus skills: [[src:lww312-s8-ml05]]", [c], _ctx(64)
    )
    assert "you'll find this lesson" not in out
    assert "[[src:" not in out                 # still swept
    assert out.rstrip().endswith(":")          # the lead-in survives intact


def test_5b_marker_on_a_closing_question_gets_NO_citation():
    """(2b) A '?' closer (Brady's 'Does this make sense?') must not carry a
    citation jammed after it. Kills: appending a sentence after the question."""
    c = _chunk("lww312-s8-ml05", 64)
    out = resolve_markers(
        "Does this make sense? [[src:lww312-s8-ml05]]", [c], _ctx(64)
    )
    assert "you'll find this lesson" not in out
    assert "[[src:" not in out
    assert out.rstrip().endswith("?")


def test_6_multi_page_citation_on_one_line_is_sorted_ascending():
    """(2c) Pages name locations in a PHYSICAL book, read front-to-back, so a
    multi-page list ascends (matching Brady's approved 'pages 97, 111'). Kills:
    emitting the pages in the model's pointer order."""
    # Structurally-bare ids (all-digit fragments -> indeterminate identity) so
    # the gate does not enter — this test isolates ORDER, not corroboration.
    late = _chunk("lww312-s8-ml05", 124)
    early = _chunk("lww312-s8-ml06", 64)
    out = resolve_markers(
        "Two spots for this. [[src:lww312-s8-ml05]] [[src:lww312-s8-ml06]]",
        [late, early], _ctx(124, 64),
    )
    assert "pages 64, 124." in out


# ---------------------------------------------------------------------------
# The deterministic reproduction gate — the real recert-P09 transcript
# ---------------------------------------------------------------------------

_P09 = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "campaign" / "dogfood" / "transcripts" / "recert-P09.jsonl"
)


def _p09_turn(turn_index):
    """Reconstruct (chunks, retrieved_context) from a real P09 turn the way the
    resolver reads them: chunk_id + book title + page parsed out of the
    assembled context's block headers (``sources`` carries no page)."""
    rec = [json.loads(l) for l in _P09.read_text().splitlines() if l.strip()][turn_index]
    ctx = rec["retrieved_context"]
    chunks = []
    for line in ctx.splitlines():
        sm = re.match(r"\[\d+\] Source: (\S+)", line)
        if not sm:
            continue
        bm = re.search(r"Book:\s*([^|]+?)\s*(?:\||$)", line)
        pm = re.search(r"Page:\s*(\d+)", line)
        chunks.append(
            _Chunk(
                source_document=(bm.group(1).strip() if bm else _TEAL),
                page_number=(int(pm.group(1)) if pm else None),
                chunk_id=sm.group(1),
            )
        )
    return chunks, ctx


@pytest.mark.skipif(not _P09.exists(), reason="recert-P09 transcript not present")
def test_P09_turn1_pizza_claim_marking_one_rubric_is_SILENT():
    """The exact recorded defect: turn 1 ('4th grade') drifted, the real pizza
    chunk was ABSENT, and a pizza claim marking the retrieved decoy
    ``one-rubric-all-writing-units`` (p.57, page present in context) cited p.57.
    With the identity gate: silence."""
    chunks, ctx = _p09_turn(1)
    assert any(c.chunk_id == _RUBRIC_ID for c in chunks)   # the decoy is really here
    assert not any("table-top-leg-sentences" in c.chunk_id for c in chunks)  # pizza absent
    claim = "For 4th grade, use the 3-12 pizza-table lesson."
    assert resolve_attribution(_RUBRIC_ID, chunks, ctx, claim_text=claim) is None
    out = resolve_markers(f"{claim} [[src:{_RUBRIC_ID}]]", chunks, ctx)
    assert "you'll find this lesson" not in out
    assert "p.57" not in out


@pytest.mark.skipif(not _P09.exists(), reason="recert-P09 transcript not present")
def test_P09_turn0_pizza_claim_marking_the_real_chunk_CITES_p64():
    """The control: turn 0 DID retrieve the real pizza chunk (p.64), so a pizza
    claim marking it must still cite p.64. Proves the gate discriminates rather
    than blanket-silencing pizza claims."""
    chunks, ctx = _p09_turn(0)
    assert resolve_attribution(
        _PIZZA_ID, chunks, ctx,
        claim_text="the pizza-table / table-top leg sentences lesson",
    ) == (_TEAL_TITLE, 64)
    out = resolve_markers(
        f"Yes — there is a pizza-table lesson. [[src:{_PIZZA_ID}]]", chunks, ctx
    )
    assert "you'll find this lesson on p.64." in out
