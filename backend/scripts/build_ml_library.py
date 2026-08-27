"""Phase 4 — Build the Scripted ML Library from existing Launch book chunks.

Each library entry is a complete mini-lesson with:
  - ml_id (unique)
  - skill_title (from chunk)
  - hyde_summaries (list of hypothetical user queries)
  - grade_levels (e.g., ["3-5", "6-8"])
  - writing_modes (derived from pie_tags)
  - pie_tags (flat list across bands)
  - lesson_triggers
  - book_reference
  - complete_ml_text (chunk content, verbatim)
  - source_document
  - priority_tier (1=Launch book, 2=SKILL template, 3=other)

HyDE strategy:
  - Auto-generate skeletal HyDEs from skill_title + grade + mode
  - Manually override for Brady-critical lessons via data/hyde_overrides.json

Usage:
    python3 scripts/build_ml_library.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = ROOT / "chunks"
DATA_DIR = ROOT / "data"
LIBRARY_PATH = DATA_DIR / "scripted_ml_library.json"
HYDE_OVERRIDES_PATH = DATA_DIR / "hyde_overrides.json"


# ---------------------------------------------------------------------------
# HyDE generation
# ---------------------------------------------------------------------------


def _grade_band_to_human(band: str) -> str:
    """Convert grade band key to human phrasing for HyDE summaries."""
    mapping = {
        "K-2": "K-2",
        "3-5": "3rd-5th grade",
        "6-8": "6th-8th grade / middle school",
        "9-12": "9th-12th grade / high school",
    }
    return mapping.get(band, band)


def _mode_to_human(mode: str) -> str:
    return {"P": "persuasive", "I": "informative", "E": "narrative"}.get(mode, mode.lower())


def auto_generate_hyde(
    skill_title: str,
    grade_levels: list[str],
    writing_modes: list[str],
) -> list[str]:
    """Auto-generate skeletal HyDE summaries.

    Returns 3-5 hypothetical user queries that the lesson should match.
    These are templates — manually improve for critical lessons via overrides.
    """
    summaries: list[str] = []

    # Template 1: Direct ask
    grade_phrase = _grade_band_to_human(grade_levels[0]) if grade_levels else ""
    summaries.append(f"How do I teach {skill_title} to {grade_phrase} students?")

    # Template 2: Lesson request
    summaries.append(f"Give me a mini-lesson on {skill_title} for {grade_phrase}")

    # Template 3: Mode-specific (if any mode detected)
    if writing_modes:
        mode_phrase = _mode_to_human(writing_modes[0])
        summaries.append(f"Lesson on {skill_title} for {mode_phrase} writing")

    # Template 4: What is a lesson for X
    summaries.append(f"What is a lesson for {skill_title}?")

    # Template 5: Scripted request
    summaries.append(f"Show me the scripted mini-lesson on {skill_title}")

    return summaries[:5]


# ---------------------------------------------------------------------------
# Entry construction
# ---------------------------------------------------------------------------


def chunk_to_library_entry(chunk: dict, hyde_overrides: dict[str, list[str]]) -> dict:
    """Convert a qualifying chunk into a library entry."""
    ml_id = f"lib-{chunk['chunk_id']}"
    skill_title = chunk.get("skill_title", "")

    # Priority-band info (which bands the pacing guide flags as essential) —
    # used by Phase 6 re-ranking, NOT for grade-compatibility gating.
    pie_tags_by_band = chunk.get("pie_tags_by_band") or {}

    # Collect all modes across grade bands
    all_mode_tags: set[str] = set()
    for band_tags in pie_tags_by_band.values():
        all_mode_tags.update(band_tags)
    mode_tag_to_name = {"P": "Persuade", "I": "Inform", "E": "Entertain"}
    writing_modes = sorted({mode_tag_to_name.get(t, t) for t in all_mode_tags})

    # grade_levels = bands where this lesson is APPLICABLE (teacher can use it),
    # derived from the book's audience. A Launch 3-12 lesson is applicable to
    # any grade 3-12 even if pacing only flags it as essential for 6-8 and 9-12.
    book_grade = (chunk.get("grade_level") or "").strip()
    if book_grade in ("3-12", "3–12"):
        grade_levels = ["3-5", "6-8", "9-12"]
    elif book_grade in ("K-2", "K–2"):
        grade_levels = ["K-2"]
    elif book_grade:
        grade_levels = [book_grade]
    else:
        grade_levels = sorted(pie_tags_by_band.keys())

    # HyDE summaries — override wins over auto-generated
    hyde = hyde_overrides.get(ml_id) or auto_generate_hyde(
        skill_title, grade_levels, sorted(all_mode_tags),
    )

    return {
        "ml_id": ml_id,
        "skill_title": skill_title,
        "hyde_summaries": hyde,
        "grade_levels": grade_levels,
        "writing_modes": writing_modes,
        "pie_tags": sorted(all_mode_tags),
        "pie_tags_by_band": pie_tags_by_band,  # preserve per-band granularity
        "lesson_triggers": chunk.get("lesson_trigger") or [],
        "book_reference": chunk.get("book_reference"),
        "page_number": chunk.get("page_number"),
        "source_document": chunk.get("source_document"),
        "source_chunk_id": chunk.get("chunk_id"),
        "complete_ml_text": chunk.get("content", "").strip(),
        "priority_tier": 1,  # Launch book
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _load_existing_entries() -> list[dict]:
    """The library as it stands on disk (empty list if there is none yet)."""
    if not LIBRARY_PATH.exists():
        return []
    with open(LIBRARY_PATH) as f:
        return json.load(f).get("entries", [])


def assert_safe_to_write(new_entries: list[dict], existing_entries: list[dict]) -> None:
    """Refuse to overwrite the library with a smaller or lossy rebuild.

    This script writes LIBRARY_PATH unconditionally, and its chunk selector
    (``book_name in ("Teal", "K-2")``) matches ZERO of the 710 corpus chunks —
    which now carry book_name of None / "Launching the Writers Workshop 3-12" /
    "...K-2". So running it wrote ``{"entries": []}`` and exited 0, silently
    destroying all 214 entries. Nothing caught that, because nothing compared
    the output to what was already there.

    The library is also NOT reproducible from this builder even with the
    selector repaired: the 31 ``content_type == 'lesson_script'`` entries
    (Brady's own 24 MLs + the 7 drawing/labeling) have ``book_name = None`` and
    were never produced here. So this guard is not a stopgap until someone
    fixes the selector — a rebuild must never be able to drop a stored entry,
    full stop.

    To repair FIELD drift (page/modes/tags), use
    ``scripts/reconcile_ml_library.py``, which is payload-only and cannot
    invalidate the embedding index. Do not reach for this script.

    Raises SystemExit (rather than returning a bool) so it fails closed at the
    call site even if a caller ignores the result.
    """
    existing_ids = {e.get("ml_id") for e in existing_entries}
    new_ids = {e.get("ml_id") for e in new_entries}
    dropped = existing_ids - new_ids
    if dropped:
        raise SystemExit(
            f"REFUSING to write: the rebuild drops {len(dropped)} of "
            f"{len(existing_ids)} stored entries "
            f"(e.g. {sorted(d for d in dropped if d)[:3]}).\n"
            f"  This script's selector matches "
            f"{len(new_entries)} chunk(s); the library holds "
            f"{len(existing_entries)} entries.\n"
            f"  It cannot reproduce the 31 lesson_script entries at all.\n"
            f"  For field drift use: python3 scripts/reconcile_ml_library.py"
        )


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)

    # Load HyDE overrides if present
    hyde_overrides: dict[str, list[str]] = {}
    if HYDE_OVERRIDES_PATH.exists():
        with open(HYDE_OVERRIDES_PATH) as f:
            hyde_overrides = json.load(f)

    # Collect qualifying chunks
    candidates: list[dict] = []
    for chunk_file in sorted(CHUNKS_DIR.glob("*.json")):
        with open(chunk_file) as f:
            chunks = json.load(f)
        for c in chunks:
            # Launch book ML chunks with title + substantive content
            if (
                c.get("book_name") in ("Teal", "K-2")
                and c.get("skill_title")
                and c.get("ml_number") is not None
                and len((c.get("content") or "").strip()) >= 500
            ):
                candidates.append(c)

    # Prioritize chunks with pie_tags_by_band (Brady's essential MLs)
    # Sort: priority (pie_tags first), then by book+chapter+ml_number
    def sort_key(c):
        has_pie = 0 if c.get("pie_tags_by_band") else 1
        book = c.get("book_name", "")
        ch = c.get("chapter_number") or 0
        ml = c.get("ml_number") or 0
        return (has_pie, book, ch, ml)

    candidates.sort(key=sort_key)

    # Build entries
    entries = [chunk_to_library_entry(c, hyde_overrides) for c in candidates]

    # Fail closed BEFORE the unconditional overwrite below (recert 2026-07-16).
    assert_safe_to_write(entries, _load_existing_entries())

    # Write library
    library = {
        "description": "Scripted ML Library — complete mini-lessons with HyDE summaries for semantic matching. Phase 4 of BRADY-ALIGNMENT-PLAN.md. Verbatim-first retrieval: when a user asks for a lesson, the pipeline pre-checks this library. High-confidence matches bypass generation and return complete_ml_text verbatim.",
        "entries": entries,
    }
    with open(LIBRARY_PATH, "w") as f:
        json.dump(library, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"ML library saved → {LIBRARY_PATH.relative_to(ROOT)}")
    print(f"Total entries:              {len(entries)}")
    with_pie = sum(1 for e in entries if e["pie_tags"])
    print(f"Entries with pie_tags:      {with_pie}")
    with_trigger = sum(1 for e in entries if e["lesson_triggers"])
    print(f"Entries with lesson_triggers: {with_trigger}")
    with_page = sum(1 for e in entries if e["page_number"])
    print(f"Entries with page_number:   {with_page}")
    with_override = sum(1 for e in entries if e["ml_id"] in hyde_overrides)
    print(f"Entries with custom HyDE:   {with_override} (of {len(hyde_overrides)} overrides)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
