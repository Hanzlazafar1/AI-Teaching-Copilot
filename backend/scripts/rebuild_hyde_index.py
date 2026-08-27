"""Phase 11.12 — idempotent HyDE embedding regeneration.

Reuses cached embeddings for library entries whose HyDE summaries haven't
changed since the last run. Only entries whose content fingerprint differs
(or whose entries are brand-new, or whose embeddings are missing) trigger
an OpenAI call. Entries removed from the library are pruned from the cache.

Usage:

    # Normal — re-embed only entries that changed:
    python3 scripts/rebuild_hyde_index.py

    # Dry-run — show the diff, don't call OpenAI, don't write the index:
    python3 scripts/rebuild_hyde_index.py --dry-run

    # Force — re-embed every entry (rare; useful after a library-wide fix
    # or when you suspect the cache is corrupt):
    python3 scripts/rebuild_hyde_index.py --full

A model change (e.g. OPENAI_EMBEDDING_MODEL gets upgraded) auto-triggers
--full behavior — you can't mix embeddings from two models in one index.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import settings
from retrieval.embedder import embed_query
from retrieval.hyde_index import (
    IndexDiff,
    compute_fingerprint,
    diff_library_against_cache,
    load_index_with_fingerprints,
    save_index_with_fingerprints,
)
from retrieval.ml_library import MLLibrary

INDEX_PATH = ROOT / "data" / "ml_library_embeddings.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Re-embed ML library HyDE summaries, only for entries "
                    "whose content has changed since the last build."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be re-embedded; don't call OpenAI or write the index.",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Re-embed every entry regardless of cache state.",
    )
    p.add_argument(
        "--index-path",
        type=Path,
        default=INDEX_PATH,
        help=f"Path to the embedding index JSON (default: {INDEX_PATH}).",
    )
    return p.parse_args()


def _print_report(diff: IndexDiff, *, dry_run: bool, model: str) -> None:
    print(f"Model: {model}")
    print(f"Index file: {INDEX_PATH.relative_to(ROOT)}")
    print(f"{'[DRY RUN]' if dry_run else '[LIVE]'} Plan:")
    for line in diff.as_report_lines():
        print(line)
    if diff.to_embed:
        # Show first few so the operator can eyeball what's changing without
        # drowning them if they did a library-wide rewrite.
        shown = diff.to_embed[:10]
        tail = f" (+{len(diff.to_embed) - len(shown)} more)" if len(diff.to_embed) > len(shown) else ""
        print(f"  changed ml_ids: {', '.join(shown)}{tail}")


async def _embed_entries_async(lib: MLLibrary, ml_ids_to_embed: list[str]) -> dict[str, list[list[float]]]:
    """Embed every HyDE for each listed ml_id. Returns a fresh embedding map
    (not merged with any cache — the caller does the merge so the flow is
    explicit)."""
    fresh: dict[str, list[list[float]]] = {}
    by_id = {e.ml_id: e for e in lib.entries}
    total_hydes = sum(
        len(by_id[mid].hyde_summaries)
        for mid in ml_ids_to_embed
        if mid in by_id
    )
    print(f"Embedding {len(ml_ids_to_embed)} entries ({total_hydes} HyDEs)...")
    t0 = time.time()
    for i, mid in enumerate(ml_ids_to_embed, 1):
        entry = by_id.get(mid)
        if entry is None:
            continue
        vectors: list[list[float]] = []
        for hyde in entry.hyde_summaries:
            vec = await embed_query(hyde)
            vectors.append(vec)
        fresh[mid] = vectors
        if i % 10 == 0 or i == len(ml_ids_to_embed):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  [{i}/{len(ml_ids_to_embed)}] {rate:.1f} entries/s")
    dt = time.time() - t0
    print(f"Embedding done in {dt:.1f}s")
    return fresh


async def main() -> int:
    args = _parse_args()
    model = settings.openai_embedding_model

    lib = MLLibrary.load()
    print(f"Library loaded: {lib.size} entries")

    cached_embeddings, cached_fingerprints, cached_model = (
        load_index_with_fingerprints(args.index_path)
    )
    if cached_model and cached_model != model:
        print(
            f"Model mismatch: cache={cached_model!r} current={model!r} "
            "— forcing full rebuild."
        )

    diff = diff_library_against_cache(
        lib.entries,
        cached_embeddings=cached_embeddings,
        cached_fingerprints=cached_fingerprints,
        model=model,
        cached_model=cached_model,
        force=args.full,
    )
    _print_report(diff, dry_run=args.dry_run, model=model)

    if args.dry_run:
        return 0
    if not diff.to_embed and not diff.orphaned:
        print("No-op — index already up to date.")
        return 0

    # Do the embedding work.
    fresh = await _embed_entries_async(lib, diff.to_embed)

    # Merge: reused cache entries + freshly embedded + drop orphaned.
    merged_embeddings: dict[str, list[list[float]]] = {
        mid: cached_embeddings[mid] for mid in diff.reused
    }
    merged_embeddings.update(fresh)

    # Recompute fingerprints for the final set — every entry in the output
    # must have its current fingerprint, not whatever the old cache had.
    by_id = {e.ml_id: e for e in lib.entries}
    merged_fingerprints: dict[str, str] = {}
    for mid in merged_embeddings:
        entry = by_id[mid]
        merged_fingerprints[mid] = compute_fingerprint(
            entry.hyde_summaries, model
        )

    save_index_with_fingerprints(
        args.index_path,
        embeddings=merged_embeddings,
        fingerprints=merged_fingerprints,
        model=model,
    )
    size_mb = args.index_path.stat().st_size / (1024 * 1024)
    print(
        f"Saved → {args.index_path.relative_to(ROOT)} "
        f"({size_mb:.1f} MB, {len(merged_embeddings)} entries)"
    )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
