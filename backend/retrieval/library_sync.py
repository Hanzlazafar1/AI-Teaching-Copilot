"""Single source of truth for the ML library's chunk-derived payload.

``data/scripted_ml_library.json`` is a PROJECTION of the corpus chunks: an
entry's page, writing modes, PIE tags and lesson triggers all belong to its
source chunk (``entry.source_chunk_id`` — resolves 214/214). Only
``hyde_summaries`` are authored separately.

**Reconciling this payload cannot invalidate the embedding index.**
``retrieval.hyde_index.compute_fingerprint`` hashes ``(model, [hydes])`` and
nothing else (`hyde_index.py:45-61`), so page/mode/tag edits leave every
fingerprint — and therefore every cached vector — valid. That is what makes the
payload-only reconcile safe, and it is the same reasoning as the F66 Option-B
Qdrant update (content unchanged → vectors already correct).

Both ``scripts/reconcile_ml_library.py`` and ``tests/unit/test_ml_library_sync``
derive from THIS module, so the repair and the invariant that polices it can
never drift apart (the S3 `deferred_skills()` pattern — one function, two
consumers, agreement by construction).

WHY this exists (recert 2026-07-16): 132 of 214 entries carried no page and no
writing_modes while their chunks carried both, and the Snapple entry was tagged
``['Inform']`` while its own book text says "Writing Mode: All (Persuasive,
Informative, Narrative)" — false-blocking the V2 gate on a correct match.
``scripts/build_ml_library.py:109`` derives ``writing_modes`` from
``pie_tags_by_band`` (which bands the PACING GUIDE flags as essential) and
ignores the chunk's structured ``writing_mode`` (which modes the BOOK says the
lesson APPLIES to). Those are different questions; the V2 gate wants
applicability. Do NOT re-run that builder to fix this — see its guard.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = _ROOT / "chunks"
LIBRARY_PATH = _ROOT / "data" / "scripted_ml_library.json"

# A chunk tagged writing_mode="all" applies to every mode. It is expanded to the
# three explicit modes rather than stored as the literal "all" because the two
# consumers read the list differently and only the expansion satisfies both:
#   * validation via retrieval.library_precheck._mode_compatible special-cases
#     "all" and would accept either form;
#   * _catalog_by_metadata (:261) does an EXACT token match, so a literal "all"
#     would silently stop matching a "persuade" browse — the entry would vanish
#     from the catalog it belongs in.
# Expanding says what the book says, and both consumers then read it correctly
# with no special case.
WRITING_MODE_ALL: tuple[str, ...] = ("Entertain", "Inform", "Persuade")


def writing_modes_from_chunk(chunk: dict[str, Any]) -> list[str]:
    """The modes the BOOK says this lesson applies to (authority for V2)."""
    mode = (chunk.get("writing_mode") or "").strip()
    if not mode:
        return []
    if mode.lower() == "all":
        return list(WRITING_MODE_ALL)
    return [mode]


def pie_tags_from_chunk(chunk: dict[str, Any]) -> list[str]:
    """Union of the per-band PIE tags — which modes the pacing guide flags as
    ESSENTIAL. Deliberately NOT the same question as writing_modes above."""
    tags: set[str] = set()
    for band_tags in (chunk.get("pie_tags_by_band") or {}).values():
        tags.update(band_tags or [])
    return sorted(tags)


def expected_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    """The chunk-derived fields an entry MUST carry, given its source chunk.

    Sorted/normalized so the invariant is order-insensitive: the tag lists are
    sets semantically, and one entry differed from its chunk by ordering alone.
    """
    return {
        "page_number": chunk.get("page_number"),
        "writing_modes": writing_modes_from_chunk(chunk),
        "pie_tags": pie_tags_from_chunk(chunk),
        "pie_tags_by_band": {
            band: sorted(tags or [])
            for band, tags in (chunk.get("pie_tags_by_band") or {}).items()
        },
        "lesson_triggers": sorted(chunk.get("lesson_trigger") or []),
    }


def actual_payload(entry: dict[str, Any]) -> dict[str, Any]:
    """The same fields as stored on the entry, normalized identically so the
    comparison is apples-to-apples."""
    return {
        "page_number": entry.get("page_number"),
        "writing_modes": sorted(entry.get("writing_modes") or []),
        "pie_tags": sorted(entry.get("pie_tags") or []),
        "pie_tags_by_band": {
            band: sorted(tags or [])
            for band, tags in (entry.get("pie_tags_by_band") or {}).items()
        },
        "lesson_triggers": sorted(entry.get("lesson_triggers") or []),
    }


def _normalize_expected(payload: dict[str, Any]) -> dict[str, Any]:
    """expected_payload with the same list-sorting actual_payload applies."""
    out = dict(payload)
    out["writing_modes"] = sorted(out["writing_modes"])
    return out


def load_corpus_chunks() -> dict[str, dict[str, Any]]:
    """Every corpus chunk, keyed by chunk_id. Mirrors the loading in
    scripts/build_ml_library.py (chunk files are JSON lists)."""
    chunks: dict[str, dict[str, Any]] = {}
    for path in sorted(CHUNKS_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            for chunk in json.load(f):
                cid = chunk.get("chunk_id")
                if cid:
                    chunks[cid] = chunk
    return chunks


def load_library() -> dict[str, Any]:
    with open(LIBRARY_PATH, encoding="utf-8") as f:
        return json.load(f)


def diff_entry(entry: dict[str, Any], chunk: dict[str, Any]) -> dict[str, tuple]:
    """Fields where the entry disagrees with its chunk -> (actual, expected).
    Empty dict = in sync."""
    want = _normalize_expected(expected_payload(chunk))
    have = actual_payload(entry)
    return {k: (have[k], want[k]) for k in want if have[k] != want[k]}


def audit_library() -> tuple[dict[str, dict[str, tuple]], list[str]]:
    """(out-of-sync entries by ml_id, ml_ids whose source_chunk_id is missing).

    Pure read — used by both the reconcile script and the in-sync test.
    """
    chunks = load_corpus_chunks()
    drift: dict[str, dict[str, tuple]] = {}
    unresolved: list[str] = []
    for entry in load_library()["entries"]:
        chunk = chunks.get(entry.get("source_chunk_id"))
        if chunk is None:
            unresolved.append(entry.get("ml_id"))
            continue
        d = diff_entry(entry, chunk)
        if d:
            drift[entry["ml_id"]] = d
    return drift, unresolved
