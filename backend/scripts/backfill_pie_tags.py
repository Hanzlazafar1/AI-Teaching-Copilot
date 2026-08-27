"""Backfill pie_tags_by_band on Launch-book scripted-lesson chunks.

Root cause of R2-H1 (narrative retrieval miss): 128 Launch-book scripted
MLs had empty `pie_tags_by_band`. The reranker's P1 boost
(`BOOST_PIE_TAG_BAND_MODE = 2.0`) depends on this field, so chunks with
empty pie got the fallback `BOOST_LAUNCH_ML_MODE_MATCH = 1.5` OR no boost
at all — letting lower-priority Essential Skills / Episode chunks into
top-3.

Policy:
  * mode == "all"       → all three tags [P, I, E] across the book's bands
  * mode == "Persuade"  → ["P"]  across bands
  * mode == "Inform"    → ["I"]  across bands
  * mode == "Entertain" → ["E"]  across bands

Book → bands:
  * book_name == "K-2"                 → bands = ["K-2"]
  * book_name in ("Teal", "3-12")      → bands = ["3-5", "6-8", "9-12"]
  * (anything else — non-Launch)       → not touched

Idempotent: only overwrites chunks whose pie_tags_by_band is empty / missing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = ROOT / "chunks"

MODE_TO_TAGS = {
    "all": ["P", "I", "E"],
    "Persuade": ["P"],
    "Inform": ["I"],
    "Entertain": ["E"],
    # Legacy casing defenses
    "persuade": ["P"],
    "inform": ["I"],
    "entertain": ["E"],
}


def _is_launch(chunk: dict) -> bool:
    return (
        chunk.get("book_name") in ("K-2", "Teal", "3-12")
        or "Launch" in (chunk.get("source_document") or "")
    )


def _bands_for(chunk: dict) -> list[str]:
    bn = chunk.get("book_name")
    if bn == "K-2":
        return ["K-2"]
    if bn in ("Teal", "3-12"):
        return ["3-5", "6-8", "9-12"]
    # Fall-through for Launch books without book_name field
    src = chunk.get("source_document") or ""
    if "K-2" in src:
        return ["K-2"]
    if "3-12" in src:
        return ["3-5", "6-8", "9-12"]
    return []


def main() -> int:
    total_changed = 0
    files_changed = 0
    for p in sorted(CHUNKS_DIR.glob("*.json")):
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            continue
        changed = False
        for c in data:
            if not isinstance(c, dict):
                continue
            if not _is_launch(c):
                continue
            if not c.get("is_scripted_lesson"):
                continue
            pie = c.get("pie_tags_by_band")
            if pie:  # already populated — leave alone
                continue
            mode = c.get("writing_mode", "all")
            tags = MODE_TO_TAGS.get(mode, ["P", "I", "E"])  # unknown → all three
            bands = _bands_for(c)
            if not bands:
                continue
            c["pie_tags_by_band"] = {b: list(tags) for b in bands}
            changed = True
            total_changed += 1
        if changed:
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            files_changed += 1
    print(f"Backfilled pie_tags_by_band on {total_changed} chunks across {files_changed} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
