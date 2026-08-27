"""Phase 4 — build the ML library embedding index and persist to disk.

Embeds every HyDE summary in data/scripted_ml_library.json using
retrieval/embedder.py (OpenAI text-embedding-3-large) and writes the
result to data/ml_library_embeddings.json.

The pipeline calls MLLibrary.load_index() at boot to avoid re-embedding
~800 HyDEs every time (which would add ~30s to cold starts).

Usage:
    python3 scripts/build_ml_library_index.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.embedder import embed_query
from retrieval.ml_library import MLLibrary

INDEX_PATH = ROOT / "data" / "ml_library_embeddings.json"


async def main() -> int:
    lib = MLLibrary.load()
    total_hydes = sum(len(e.hyde_summaries) for e in lib.entries)
    print(f"Library: {lib.size} entries, {total_hydes} HyDEs to embed")

    t0 = time.time()
    await lib.build_index_async(embed_query)
    dt = time.time() - t0
    print(f"Embedded in {dt:.1f}s ({total_hydes / dt:.1f} HyDEs/s)")

    lib.save_index(INDEX_PATH)
    size_mb = INDEX_PATH.stat().st_size / (1024 * 1024)
    print(f"Index saved → {INDEX_PATH.relative_to(ROOT)} ({size_mb:.1f} MB)")

    verify = MLLibrary.load()
    verify.load_index(INDEX_PATH)
    assert verify.has_embeddings(), "Index load verification failed"
    covered = sum(1 for e in verify.entries if verify._hyde_embeddings.get(e.ml_id))
    print(f"Verify: {covered}/{verify.size} entries have embeddings on disk reload")
    assert covered == verify.size, f"Missing embeddings for {verify.size - covered} entries"

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
