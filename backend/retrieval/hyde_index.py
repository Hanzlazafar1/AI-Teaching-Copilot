"""Phase 11.12 — idempotent HyDE embedding cache with content fingerprints.

Embeddings are expensive (one OpenAI API call per HyDE summary — the library
has ~1254 summaries today). Hand-authoring HyDEs for one library entry should
cost 1 API call to re-embed, not 1254. This module lets the regen script
cheaply answer "which entries' HyDEs have actually changed since the cache
was built?" and re-embed only those.

Fingerprint shape:

    sha256( model_name  ||  serialized_hyde_summaries )

Why model is part of the hash: upgrading to ``text-embedding-3-xl`` (say)
invalidates every cached vector — the dimensions and semantics change. Mixing
vectors from two models in one index is a subtle bug we'd rather force to
"regenerate everything" than silently allow.

Why only HyDEs (not skill_title, book_reference, etc.): those fields don't
feed into the embedding prompt — they're retrieval-time metadata. Changing
``skill_title`` should not force a re-embed.

File format (additive, backward-compatible with the old shape):

    {
      "model":        "text-embedding-3-large",
      "fingerprints": { ml_id: "sha256-hex" },
      "embeddings":   { ml_id: [[...], [...]] }
    }

Old files with just ``{"embeddings": {...}}`` still load — we just treat every
fingerprint as stale (safest default: re-embed everything).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from retrieval.ml_library import LibraryEntry


def compute_fingerprint(hyde_summaries: Iterable[str], model: str) -> str:
    """Stable hash of ``(model, [hyde_1, hyde_2, ...])``.

    Order-sensitive: embeddings are stored as a positional list, so swapping
    two HyDEs DOES require a re-embed (the list index no longer maps to the
    same text). We deliberately do not sort.

    Uses ``json.dumps`` with ``ensure_ascii=False`` to keep the hash stable
    across locale settings but handle any unicode (smart quotes etc.) in
    authored HyDEs.
    """
    payload = json.dumps(
        {"model": model, "hydes": list(hyde_summaries)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IndexDiff:
    """Outcome of comparing the library against the cached index.

    Totals always sum to ``len(library.entries)`` — every entry is in
    exactly one of these buckets.
    """

    to_embed: list[str]       # ml_ids whose HyDEs changed (or no cache).
    reused: list[str]         # ml_ids the cache covers correctly.
    orphaned: list[str]       # ml_ids in the cache but no longer in library.

    @property
    def total_changed(self) -> int:
        return len(self.to_embed)

    def as_report_lines(self) -> list[str]:
        return [
            f"  to_embed: {len(self.to_embed):>4}  (changed HyDEs or first-time)",
            f"  reused:   {len(self.reused):>4}  (unchanged, cache hit)",
            f"  orphaned: {len(self.orphaned):>4}  (deleted from library, dropping)",
        ]


def load_index_with_fingerprints(path: Path) -> tuple[
    dict[str, list[list[float]]],
    dict[str, str],
    Optional[str],
]:
    """Return (embeddings, fingerprints, model_name).

    Old-format files (no fingerprints) return empty ``fingerprints`` dict —
    every entry is then treated as stale, which is the safe default.
    Missing files return three empty values (full rebuild).
    """
    if not path.exists():
        return {}, {}, None
    with open(path) as f:
        payload = json.load(f)
    embeddings: dict[str, list[list[float]]] = payload.get("embeddings") or {}
    fingerprints: dict[str, str] = payload.get("fingerprints") or {}
    model: Optional[str] = payload.get("model") or None
    return embeddings, fingerprints, model


def save_index_with_fingerprints(
    path: Path,
    *,
    embeddings: dict[str, list[list[float]]],
    fingerprints: dict[str, str],
    model: str,
) -> None:
    """Write an index file in the new format.

    Backward-compatible reads still work (old :func:`MLLibrary.load_index`
    only peeks at ``embeddings``). New tooling can read the extra fields.
    """
    payload = {
        "model": model,
        "fingerprints": fingerprints,
        "embeddings": embeddings,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)


def diff_library_against_cache(
    entries: list[LibraryEntry],
    cached_embeddings: dict[str, list[list[float]]],
    cached_fingerprints: dict[str, str],
    model: str,
    *,
    cached_model: Optional[str] = None,
    force: bool = False,
) -> IndexDiff:
    """Partition library entries into to_embed / reused / orphaned.

    Rules:
      * ``force=True`` → every entry is in ``to_embed`` regardless of cache.
      * Model changed vs cache → treat as force (embedding semantics no
        longer match; whole index must be rebuilt).
      * Per-entry rule: reuse iff fingerprint matches AND embeddings present.

    Entries missing from the library but present in the cache are
    ``orphaned`` — they'll be dropped from the output so the index doesn't
    accumulate dead weight.
    """
    full_rebuild = force or (
        cached_model is not None and cached_model != model
    )

    library_ids = {e.ml_id for e in entries}
    to_embed: list[str] = []
    reused: list[str] = []

    for entry in entries:
        fp = compute_fingerprint(entry.hyde_summaries, model)
        cached_fp = cached_fingerprints.get(entry.ml_id)
        has_cached_vecs = bool(cached_embeddings.get(entry.ml_id))
        # Also require the cached list length to match — a partial cache
        # (e.g., crash mid-embed) shouldn't count as a hit.
        length_matches = (
            has_cached_vecs
            and len(cached_embeddings[entry.ml_id]) == len(entry.hyde_summaries)
        )
        if (
            not full_rebuild
            and cached_fp == fp
            and length_matches
        ):
            reused.append(entry.ml_id)
        else:
            to_embed.append(entry.ml_id)

    orphaned = sorted(set(cached_embeddings) - library_ids)
    return IndexDiff(to_embed=to_embed, reused=reused, orphaned=orphaned)
