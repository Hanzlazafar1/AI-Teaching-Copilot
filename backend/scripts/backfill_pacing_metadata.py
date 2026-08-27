"""Phase 2 backfill — apply pacing.json data to enriched chunks.

Populates pie_tags_by_band and page_number on chunks whose skill_title
matches a pacing entry. Refreshes book_reference with page number.

Usage:
    python3 scripts/extract_pacing.py           # (Phase 2.1) build pacing.json
    python3 scripts/backfill_pacing_metadata.py # (Phase 2.2) apply to chunks
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.metadata_enricher import apply_pacing_metadata  # noqa: E402

CHUNKS_DIR = ROOT / "chunks"
PACING_PATH = ROOT / "data" / "launch_book_pacing.json"


def main() -> int:
    if not PACING_PATH.exists():
        print(f"ERROR: pacing file not found: {PACING_PATH}", file=sys.stderr)
        print("Run scripts/extract_pacing.py first.", file=sys.stderr)
        return 1

    with open(PACING_PATH) as f:
        pacing = json.load(f)

    stats = {
        "section_8_13_chunks": 0,
        "section_8_13_with_pie": 0,
        "section_8_13_with_page": 0,
        "section_1_7_chunks": 0,
        "section_1_7_with_pie": 0,
        "launch_chunks": 0,
        "launch_with_pie": 0,
        "launch_with_page": 0,
    }

    for chunk_file in sorted(CHUNKS_DIR.glob("*.json")):
        with open(chunk_file) as f:
            chunks = json.load(f)

        updated: list[dict] = []
        for chunk in chunks:
            chunk = apply_pacing_metadata(chunk, pacing)
            updated.append(chunk)

            if chunk.get("book_name") in ("Teal", "K-2"):
                stats["launch_chunks"] += 1
                if chunk.get("pie_tags_by_band"):
                    stats["launch_with_pie"] += 1
                if chunk.get("page_number"):
                    stats["launch_with_page"] += 1

                ch = chunk.get("chapter_number")
                if ch and 8 <= ch <= 13:
                    stats["section_8_13_chunks"] += 1
                    if chunk.get("pie_tags_by_band"):
                        stats["section_8_13_with_pie"] += 1
                    if chunk.get("page_number"):
                        stats["section_8_13_with_page"] += 1
                elif ch and 1 <= ch <= 7:
                    stats["section_1_7_chunks"] += 1
                    if chunk.get("pie_tags_by_band"):
                        stats["section_1_7_with_pie"] += 1  # should stay 0

        with open(chunk_file, "w") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)

    print("=== Phase 2 backfill results ===\n")
    print(f"Launch book chunks:                  {stats['launch_chunks']}")
    print(f"  with pie_tags_by_band populated:   {stats['launch_with_pie']} "
          f"({pct(stats['launch_with_pie'], stats['launch_chunks'])}%)")
    print(f"  with page_number populated:        {stats['launch_with_page']} "
          f"({pct(stats['launch_with_page'], stats['launch_chunks'])}%)")
    print()
    print(f"Section 8-13 ML chunks:              {stats['section_8_13_chunks']}")
    print(f"  with pie_tags_by_band populated:   {stats['section_8_13_with_pie']} "
          f"({pct(stats['section_8_13_with_pie'], stats['section_8_13_chunks'])}%)")
    print(f"  with page_number populated:        {stats['section_8_13_with_page']} "
          f"({pct(stats['section_8_13_with_page'], stats['section_8_13_chunks'])}%)")
    print()
    print(f"Section 1-7 chunks (should not get PIE tags): {stats['section_1_7_chunks']}")
    print(f"  with pie_tags_by_band populated:   {stats['section_1_7_with_pie']} "
          f"(expected 0 — PIE tags are only for mode-specific MLs)")

    return 0


def pct(num: int, den: int) -> int:
    return int(100 * num / den) if den else 0


if __name__ == "__main__":
    sys.exit(main())
