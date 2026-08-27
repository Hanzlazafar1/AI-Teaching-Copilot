"""Phase 3 backfill — apply trigger dictionary to chunks.

Scans every chunk's content + skill_title + section_name + strategy_name
for synonyms of known Smekens triggers. Populates lesson_trigger list.

Usage:
    python3 scripts/backfill_triggers.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.metadata_enricher import tag_chunk_with_triggers  # noqa: E402

CHUNKS_DIR = ROOT / "chunks"
TRIGGERS_PATH = ROOT / "data" / "skill_triggers.json"


def main() -> int:
    if not TRIGGERS_PATH.exists():
        print(f"ERROR: {TRIGGERS_PATH} not found", file=sys.stderr)
        return 1

    with open(TRIGGERS_PATH) as f:
        data = json.load(f)
    triggers = data["triggers"]

    trigger_counts: Counter[str] = Counter()
    chunks_with_triggers = 0
    total_chunks = 0

    for chunk_file in sorted(CHUNKS_DIR.glob("*.json")):
        with open(chunk_file) as f:
            chunks = json.load(f)

        updated: list[dict] = []
        for chunk in chunks:
            chunk = tag_chunk_with_triggers(chunk, triggers)
            updated.append(chunk)
            total_chunks += 1
            tags = chunk.get("lesson_trigger") or []
            if tags:
                chunks_with_triggers += 1
                for t in tags:
                    trigger_counts[t] += 1

        with open(chunk_file, "w") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)

    print(f"Total chunks:                {total_chunks}")
    print(f"Chunks with ≥1 trigger tag:  {chunks_with_triggers} ({100*chunks_with_triggers//total_chunks}%)")
    print()
    print("Trigger tag distribution (chunks per trigger):")
    for name, n in trigger_counts.most_common():
        print(f"  {name:25s}  {n}")

    missing = set(triggers.keys()) - set(trigger_counts.keys())
    if missing:
        print()
        print(f"Triggers with NO matches in any chunk:")
        for m in sorted(missing):
            print(f"  {m}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
