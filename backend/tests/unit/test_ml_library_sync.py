"""The ML library must stay in sync with the corpus chunks it projects.

Recert 2026-07-16 (P1): 132 of 214 entries carried no page_number and no
writing_modes while their source chunks carried both, and the Snapple entry was
tagged ['Inform'] while its own book text reads "Writing Mode: All (Persuasive,
Informative, Narrative)" — which false-blocks the V2 gate on a correct match.
Nothing noticed, because nothing ever compared the two.

These are INVARIANTS, not instance tests: they fail on ANY future drift between
an entry and its chunk, whatever the field, and they derive from the same
retrieval.library_sync functions the reconcile script uses — so the repair and
the check cannot disagree by construction.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from retrieval.library_sync import (
    WRITING_MODE_ALL,
    audit_library,
    load_corpus_chunks,
    load_library,
    writing_modes_from_chunk,
)

_ROOT = Path(__file__).resolve().parents[2]


def test_every_entry_resolves_to_a_corpus_chunk() -> None:
    """An entry whose source chunk is gone cannot be checked OR repaired — it
    is unfalsifiable data. Must never happen."""
    _, unresolved = audit_library()
    assert unresolved == [], (
        f"{len(unresolved)} entries have a source_chunk_id with no chunk: "
        f"{unresolved[:5]}"
    )


def test_library_is_in_sync_with_its_chunks() -> None:
    """Every chunk-derived field on every entry matches its source chunk."""
    drift, _ = audit_library()
    assert drift == {}, (
        f"{len(drift)} entries drifted from their chunks. Run "
        f"`python3 scripts/reconcile_ml_library.py` (payload-only; it cannot "
        f"invalidate the embedding index — the fingerprint hashes only "
        f"(model, hydes)). First 3: "
        f"{dict(list(drift.items())[:3])}"
    )


def test_writing_mode_all_expands_to_the_three_modes() -> None:
    """A chunk tagged writing_mode='all' must expand to the three explicit
    modes, NOT the literal 'all'.

    _mode_compatible special-cases 'all' and would accept either form, but
    _catalog_by_metadata (library_precheck.py:261) does an EXACT token match —
    a literal 'all' would silently stop matching a 'persuade' browse and the
    entry would vanish from the catalog it belongs in. Expanding satisfies both
    readers with no special case.
    """
    assert writing_modes_from_chunk({"writing_mode": "all"}) == list(WRITING_MODE_ALL)
    assert writing_modes_from_chunk({"writing_mode": "All"}) == list(WRITING_MODE_ALL)
    assert writing_modes_from_chunk({"writing_mode": "Persuade"}) == ["Persuade"]
    # Absent tag stays absent — an empty list means "untagged", which
    # _mode_compatible reads as compatible-with-everything. Do not invent a mode.
    assert writing_modes_from_chunk({}) == []
    assert writing_modes_from_chunk({"writing_mode": ""}) == []


def test_snapple_entry_is_not_mode_narrowed_against_its_book() -> None:
    """The recert's headline data defect, locked.

    Brady's book text for ML #7 says "Writing Mode: All (Persuasive,
    Informative, Narrative)"; the entry was tagged ['Inform'] because
    build_ml_library.py:109 derives writing_modes from pie_tags_by_band (the
    pacing guide's ESSENTIAL bands) and ignores the chunk's structured
    writing_mode (the book's APPLICABILITY). Those are different questions and
    the V2 gate wants applicability — the narrow tag made
    _mode_compatible('Persuade', ['Inform']) False, blocking a correct match.
    """
    entries = {e["ml_id"]: e for e in load_library()["entries"]}
    snapple = next(
        (e for mid, e in entries.items() if "snapple" in mid), None
    )
    assert snapple is not None, "the Snapple entry vanished from the library"

    chunk = load_corpus_chunks()[snapple["source_chunk_id"]]
    assert "writing mode: all" in (chunk.get("content") or "").lower(), (
        "fixture drift: this lock assumes the book text still says "
        "'Writing Mode: All'"
    )
    assert sorted(snapple["writing_modes"]) == sorted(WRITING_MODE_ALL), (
        "Snapple is mode-narrowed against its own book text again"
    )

    from retrieval.library_precheck import _mode_compatible

    for mode in WRITING_MODE_ALL:
        assert _mode_compatible(mode, snapple["writing_modes"]), (
            f"V2 would false-block a correct Snapple match for {mode}"
        )


def test_library_entries_carry_a_page_where_the_book_has_one() -> None:
    """Fm5's citation is built from page_number; a missing page silently means
    'ship no citation'. 132 entries had none while their chunk did."""
    chunks = load_corpus_chunks()
    missing = [
        e["ml_id"]
        for e in load_library()["entries"]
        if not e.get("page_number")
        and chunks.get(e["source_chunk_id"], {}).get("page_number")
    ]
    assert missing == [], (
        f"{len(missing)} entries have no page_number while their chunk does: "
        f"{missing[:5]}"
    )


# ---------------------------------------------------------------------------
# The builder landmine (recert B6).
# ---------------------------------------------------------------------------


def test_builder_refuses_to_shrink_the_library() -> None:
    """scripts/build_ml_library.py must FAIL CLOSED rather than overwrite.

    Its selector filters chunks on book_name in ("Teal","K-2"); the corpus
    actually carries None / "Launching the Writers Workshop 3-12" / "...K-2",
    so it matches ZERO of 710 chunks — and it json.dumps the result
    UNCONDITIONALLY. Running it today writes {"entries": []} and exits 0,
    destroying all 214 entries. (The v1 of this recert's own spec told a future
    implementer to "fix build_ml_library.py:109 and rebuild" — which would have
    silently done exactly that.)

    The library also is NOT reproducible from this builder at all: the 31
    `content_type == 'lesson_script'` entries have book_name=None and were
    never produced by it. So "repair the selector" is not sufficient and a
    guard is not a stopgap — a rebuild must never be able to drop entries.
    """
    from scripts.build_ml_library import assert_safe_to_write

    existing = load_library()["entries"]

    # The status quo: the live selector yields nothing -> must raise, not write.
    with pytest.raises(SystemExit):
        assert_safe_to_write([], existing)

    # Dropping even one stored ml_id must fail closed.
    with pytest.raises(SystemExit):
        assert_safe_to_write(existing[:-1], existing)

    # Same set, or a superset, is allowed.
    assert_safe_to_write(existing, existing)
    assert_safe_to_write(existing + [{"ml_id": "lib-brand-new"}], existing)


def test_builder_selector_currently_matches_nothing() -> None:
    """Documents WHY the guard above is load-bearing, and will go green on its
    own if anyone ever repairs the selector. Not a failure — a tripwire."""
    chunks = list(load_corpus_chunks().values())
    selected = [c for c in chunks if c.get("book_name") in ("Teal", "K-2")]
    if selected:
        pytest.skip("selector repaired — guard remains as defence in depth")
    assert len(chunks) > 0
    assert selected == []  # the landmine, disarmed by the guard above


# ---------------------------------------------------------------------------
# I5 — the grade vocabulary must be ONE table, not two hand-kept inverses.
# ---------------------------------------------------------------------------


def test_pk1_content_is_reachable_for_early_grades() -> None:
    """recert I5: all 6 PK-1 drawing/labeling lessons were unreachable at EVERY
    concrete grade — dead data, silently.

    F67 taught retrieval/filters.py that early-writer content is tagged "PK-1"
    and must be retrieved for a grade-K/1 query (filters.py:28-33, with a
    comment stating exactly that rule). Nobody taught ml_library, whose
    _BAND_RANGES never listed PK-1 — so is_grade_compatible(["PK-1"], "K") was
    False and the grade filter dropped those entries before any threshold ran.
    """
    from retrieval.ml_library import is_grade_compatible

    assert is_grade_compatible(["PK-1"], "K")
    assert is_grade_compatible(["PK-1"], "1")
    # PK-1 means pre-K..grade 1 — it must NOT leak upward.
    assert not is_grade_compatible(["PK-1"], "2")
    assert not is_grade_compatible(["PK-1"], "5")


def test_grade_vocabulary_is_single_sourced() -> None:
    """Both the Qdrant filter and the library compatibility check must read the
    SAME table, so a future range tag cannot be taught to one and not the other
    (which is precisely how PK-1 became dead data)."""
    from retrieval import filters, grades
    from retrieval.ml_library import is_grade_compatible

    assert filters.GRADE_RANGE_MAP is grades.GRADE_RANGE_MAP

    # The library check is the inverse lookup of that one table, for every
    # grade and every tag it knows — no separate vocabulary to drift.
    for grade, tags in grades.GRADE_RANGE_MAP.items():
        for tag in tags:
            assert is_grade_compatible([tag], grade), (
                f"tag {tag!r} covers grade {grade!r} in GRADE_RANGE_MAP but "
                f"is_grade_compatible disagrees"
            )


def test_every_library_grade_tag_is_known_to_the_vocabulary() -> None:
    """A tag in the data that the vocabulary has never heard of is unreachable
    data waiting to happen — exactly PK-1's failure mode."""
    from retrieval import grades

    known = set(grades.GRADE_RANGE_MAP) | set(grades.UNIVERSAL_RANGE_TAGS)
    for tags in grades.GRADE_RANGE_MAP.values():
        known |= set(tags)

    unknown = {
        tag
        for e in load_library()["entries"]
        for tag in (e.get("grade_levels") or [])
        if tag not in known
    }
    assert unknown == set(), f"library uses grade tags the vocabulary lacks: {unknown}"
