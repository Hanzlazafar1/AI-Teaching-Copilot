"""Phase 1 enrichment — run metadata extractors on all chunk files.

Outputs:
  - chunks/*.json      : in-place update with new fields (additive only)
  - data/flagged_for_review.json : entries where any field confidence < 0.9

Usage:
    python3 scripts/enrich_chunks.py
    python3 scripts/enrich_chunks.py --dry-run   # preview without writing
    python3 scripts/enrich_chunks.py --threshold 0.8   # flag threshold

Idempotent: safe to re-run. Only adds/updates the Phase 1 fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make imports work when script is run from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.metadata_enricher import enrich_chunk  # noqa: E402


DEFAULT_THRESHOLD = 0.9
CHUNKS_DIR = ROOT / "chunks"
DATA_DIR = ROOT / "data"
FLAGGED_PATH = DATA_DIR / "flagged_for_review.json"

# Fields that are EXPECTED to have medium confidence and don't need review:
# - book_reference: page_number is filled in Phase 2; medium (0.8) is expected pre-Phase-2
# - topic_keywords: heuristic-by-design; medium (0.7) is expected
FLAGGING_EXCLUDE_FIELDS = frozenset({"book_reference", "topic_keywords"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich chunk metadata (Phase 1).")
    parser.add_argument("--dry-run", action="store_true", help="Don't write files.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="Flag for review when any field confidence < threshold (default 0.9).",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    files_processed = 0
    chunks_processed = 0
    flagged: list[dict] = []
    field_stats: dict[str, dict[str, int]] = {}

    for chunk_file in sorted(CHUNKS_DIR.glob("*.json")):
        with open(chunk_file) as f:
            data = json.load(f)

        enriched_chunks: list[dict] = []
        for chunk in data:
            enriched, confidences = enrich_chunk(chunk)
            enriched_chunks.append(enriched)
            chunks_processed += 1

            # Track per-field stats
            for field, conf in confidences.items():
                stats = field_stats.setdefault(field, {"high": 0, "medium": 0, "low": 0, "null": 0})
                if conf >= 0.9:
                    stats["high"] += 1
                elif conf >= 0.5:
                    stats["medium"] += 1
                elif conf > 0:
                    stats["low"] += 1
                else:
                    stats["null"] += 1

            # Flag if any field below threshold (excluding expected-medium fields)
            flagged_fields = {
                f: c for f, c in confidences.items()
                if 0 < c < args.threshold and f not in FLAGGING_EXCLUDE_FIELDS
            }
            if flagged_fields:
                flagged.append(
                    {
                        "chunk_id": enriched.get("chunk_id"),
                        "source_document": enriched.get("source_document"),
                        "section_name": enriched.get("section_name"),
                        "flagged_fields": flagged_fields,
                        "extracted": {
                            f: enriched.get(f)
                            for f in flagged_fields.keys()
                        },
                    }
                )

        if not args.dry_run:
            with open(chunk_file, "w") as f:
                json.dump(enriched_chunks, f, indent=2, ensure_ascii=False)
        files_processed += 1

    # Write flagged for review
    if not args.dry_run:
        with open(FLAGGED_PATH, "w") as f:
            json.dump(
                {
                    "threshold": args.threshold,
                    "total_flagged": len(flagged),
                    "field_stats": field_stats,
                    "entries": flagged,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

    # Print summary
    print(f"Files processed:  {files_processed}")
    print(f"Chunks processed: {chunks_processed}")
    print(f"Chunks flagged:   {len(flagged)} (confidence < {args.threshold})")
    if args.dry_run:
        print("DRY RUN — no files written")
    else:
        print(f"Flagged report:   {FLAGGED_PATH.relative_to(ROOT)}")
    print("\nField confidence distribution:")
    for field, stats in sorted(field_stats.items()):
        total = sum(stats.values())
        pct_high = 100 * stats["high"] / total if total else 0
        print(
            f"  {field:25s}  high={stats['high']:4d}  med={stats['medium']:3d}  "
            f"low={stats['low']:3d}  null={stats['null']:3d}  ({pct_high:.0f}% high)"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
