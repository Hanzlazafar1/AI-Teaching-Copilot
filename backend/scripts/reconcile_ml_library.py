"""Reconcile data/scripted_ml_library.json against the corpus chunks it projects.

PAYLOAD-ONLY, by construction: this script writes ONLY the chunk-derived fields
(page_number, writing_modes, pie_tags, pie_tags_by_band, lesson_triggers) and
never touches ml_id, hyde_summaries, complete_ml_text, skill_title, grade_levels
or source_chunk_id.

That is what makes it safe to run without re-embedding anything:
retrieval.hyde_index.compute_fingerprint hashes (model, [hydes]) and NOTHING
else, so every cached vector and fingerprint stays valid. Same reasoning as the
F66 Option-B Qdrant payload update (content unchanged -> vectors already right).

Do NOT "fix and re-run" scripts/build_ml_library.py instead: its selector
matches 0 of 710 corpus chunks and it overwrites unconditionally, so running it
writes {"entries": []} and exits 0. It also cannot reproduce the 31
lesson_script entries at all. This script is the repair; that one is a landmine
(now guarded).

Usage (from copilot-v4):
    python3 scripts/reconcile_ml_library.py            # dry-run: report only
    python3 scripts/reconcile_ml_library.py --apply    # write
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retrieval.library_sync import (  # noqa: E402
    LIBRARY_PATH,
    audit_library,
    expected_payload,
    load_corpus_chunks,
    load_library,
)

# Fields this script is permitted to write. Anything not listed here is
# untouchable — notably hyde_summaries, whose hash is the embedding cache key.
_WRITABLE = (
    "page_number",
    "writing_modes",
    "pie_tags",
    "pie_tags_by_band",
    "lesson_triggers",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes")
    args = ap.parse_args()

    drift, unresolved = audit_library()
    if unresolved:
        print(
            f"REFUSING: {len(unresolved)} entries have a source_chunk_id with no "
            f"chunk — they cannot be reconciled: {unresolved[:5]}"
        )
        return 1

    if not drift:
        print("library is already in sync with its chunks — nothing to do")
        return 0

    print(f"{len(drift)} entries drift from their chunks:\n")
    by_field: dict[str, int] = {}
    for ml_id, fields in drift.items():
        for field, (have, want) in fields.items():
            by_field[field] = by_field.get(field, 0) + 1
    for field, n in sorted(by_field.items(), key=lambda kv: -kv[1]):
        print(f"  {field:20s} {n:3d} entries")

    print("\n  examples:")
    for ml_id, fields in list(drift.items())[:3]:
        for field, (have, want) in fields.items():
            print(f"    {ml_id}\n      {field}: {have!r} -> {want!r}")

    if not args.apply:
        print("\nDRY RUN — re-run with --apply to write.")
        return 0

    chunks = load_corpus_chunks()
    library = load_library()
    before = {e["ml_id"]: dict(e) for e in library["entries"]}

    changed = 0
    for entry in library["entries"]:
        if entry["ml_id"] not in drift:
            continue
        want = expected_payload(chunks[entry["source_chunk_id"]])
        for field in _WRITABLE:
            entry[field] = want[field]
        changed += 1

    # Fail closed: the reconcile is payload-only, so anything outside _WRITABLE
    # changing means a bug in this script — never write in that case.
    after = {e["ml_id"]: e for e in library["entries"]}
    if set(after) != set(before):
        print("REFUSING: the entry set changed — this script must not add/remove entries")
        return 1
    for ml_id, old in before.items():
        for key, old_val in old.items():
            if key in _WRITABLE:
                continue
            if after[ml_id].get(key) != old_val:
                print(f"REFUSING: {ml_id}.{key} changed — outside the payload allow-list")
                return 1

    with open(LIBRARY_PATH, "w") as f:
        json.dump(library, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nwrote {changed} reconciled entries -> {LIBRARY_PATH}")
    print("hyde_summaries untouched -> embedding index + fingerprints stay valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
