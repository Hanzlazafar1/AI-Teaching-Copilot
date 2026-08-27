"""Scripted ML Library — Phase 4 of BRADY-ALIGNMENT-PLAN.md.

Loads data/scripted_ml_library.json and provides semantic matching via
HyDE summary embeddings. Used as a pre-check in Phase 7 of the pipeline:
  1. User asks for a mini-lesson.
  2. Pipeline embeds the query.
  3. ML Library returns candidate entries ranked by HyDE-similarity.
  4. If a candidate meets confidence + grade-compatibility thresholds,
     the library entry's complete_ml_text is returned verbatim
     (bypassing LLM generation).

Key design choices:
  - HyDE (Hypothetical Document Embedding): each entry lists hypothetical
    user queries that the lesson answers. We embed each HyDE summary and
    compare against the incoming query embedding.
  - Confidence = max cosine similarity across the entry's HyDEs.
  - Grade compatibility follows Section 11.3 of the plan.
  - No LLM-side decision: the pipeline (not an agent) decides when to
    invoke this module.

Embedding model: whatever retrieval/embedder.py exposes (currently
text-embedding-3-large). Library embeddings are computed once at load time
and cached in-process.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from retrieval.grades import UNIVERSAL_RANGE_TAGS, range_tags_for_grade

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIBRARY_PATH = ROOT / "data" / "scripted_ml_library.json"
DEFAULT_INDEX_PATH = ROOT / "data" / "ml_library_embeddings.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LibraryEntry:
    """One scripted mini-lesson in the library."""
    ml_id: str
    skill_title: str
    hyde_summaries: list[str]
    grade_levels: list[str]
    writing_modes: list[str]
    pie_tags: list[str]
    pie_tags_by_band: dict[str, list[str]]
    lesson_triggers: list[str]
    book_reference: Optional[str]
    page_number: Optional[int]
    source_document: Optional[str]
    source_chunk_id: Optional[str]
    complete_ml_text: str
    priority_tier: int

    @classmethod
    def from_dict(cls, d: dict) -> "LibraryEntry":
        return cls(
            ml_id=d["ml_id"],
            skill_title=d.get("skill_title", ""),
            hyde_summaries=d.get("hyde_summaries") or [],
            grade_levels=d.get("grade_levels") or [],
            writing_modes=d.get("writing_modes") or [],
            pie_tags=d.get("pie_tags") or [],
            pie_tags_by_band=d.get("pie_tags_by_band") or {},
            lesson_triggers=d.get("lesson_triggers") or [],
            book_reference=d.get("book_reference"),
            page_number=d.get("page_number"),
            source_document=d.get("source_document"),
            source_chunk_id=d.get("source_chunk_id"),
            complete_ml_text=d.get("complete_ml_text") or "",
            priority_tier=d.get("priority_tier", 1),
        )


@dataclass
class LibraryMatch:
    """Result of a library search."""
    entry: LibraryEntry
    confidence: float  # max cosine similarity across HyDEs
    matched_hyde: str  # the specific HyDE that produced the highest score
    grade_compatible: bool


# ---------------------------------------------------------------------------
# Grade compatibility (Section 11.3 of BRADY-ALIGNMENT-PLAN.md)
# ---------------------------------------------------------------------------


def is_grade_compatible(entry_grades: Iterable[str], user_grade: Optional[str]) -> bool:
    """Return True if the entry's grade_levels cover the user's grade.

    Matching rules:
      - User grade None → always compatible (use lesson, note its range)
      - Entry grade "all" / "K-12" → always compatible
      - Entry grade is a range tag (e.g., "3-5", "PK-1") → compatible if that
        tag is one of the tags covering the user's grade
      - Entry grade is a single grade (e.g., "4") → compatible only for exact match

    Derived from `retrieval.grades.GRADE_RANGE_MAP` — the ONE grade vocabulary —
    rather than a local band table. This used to be a hand-kept INVERSE of that
    map, and the two drifted: F67 taught the Qdrant side that early-writer
    content is tagged "PK-1" and must be retrieved for a grade-K/1 query, but
    this side never learned it, so `is_grade_compatible(["PK-1"], "K")` was
    False and all 6 PK-1 lessons were unreachable at EVERY concrete grade
    (recert I5). One table means that class of drift is now inexpressible.
    """
    if user_grade is None:
        return True

    user_grade_norm = str(user_grade).strip()
    covering = set(range_tags_for_grade(user_grade_norm))
    for eg in entry_grades:
        eg_norm = str(eg).strip()
        if eg_norm in UNIVERSAL_RANGE_TAGS:
            return True
        if eg_norm == user_grade_norm:
            return True
        if eg_norm in covering:
            return True
    return False


# ---------------------------------------------------------------------------
# Embedding math
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Library class
# ---------------------------------------------------------------------------


class MLLibrary:
    """In-memory semantic index of scripted MLs.

    Usage:
        lib = MLLibrary.load()
        await lib.build_index(embed_fn=embed_query_async)
        matches = lib.find_matches(query_embedding, user_grade="4", top_k=3)
    """

    def __init__(self, entries: list[LibraryEntry]) -> None:
        self.entries = entries
        # entry_embeddings: list of lists (one embedding per HyDE summary)
        self._hyde_embeddings: dict[str, list[list[float]]] = {}

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "MLLibrary":
        path = path or DEFAULT_LIBRARY_PATH
        with open(path) as f:
            data = json.load(f)
        entries = [LibraryEntry.from_dict(d) for d in data.get("entries", [])]
        return cls(entries)

    @property
    def size(self) -> int:
        return len(self.entries)

    def has_embeddings(self) -> bool:
        return bool(self._hyde_embeddings)

    async def build_index_async(self, embed_fn) -> None:
        """Embed every HyDE summary. embed_fn is async, takes str, returns list[float].

        Call once at startup. Safe to call multiple times (skips if already indexed).
        """
        if self._hyde_embeddings:
            return
        for entry in self.entries:
            embeddings: list[list[float]] = []
            for hyde in entry.hyde_summaries:
                vec = await embed_fn(hyde)
                embeddings.append(vec)
            self._hyde_embeddings[entry.ml_id] = embeddings
        logger.info(
            "MLLibrary index built: %d entries, %d HyDE embeddings total",
            len(self.entries),
            sum(len(v) for v in self._hyde_embeddings.values()),
        )

    def build_index_sync(self, embed_fn) -> None:
        """Sync version — embed_fn takes str, returns list[float]."""
        if self._hyde_embeddings:
            return
        for entry in self.entries:
            embeddings: list[list[float]] = []
            for hyde in entry.hyde_summaries:
                vec = embed_fn(hyde)
                embeddings.append(vec)
            self._hyde_embeddings[entry.ml_id] = embeddings

    def save_index(self, path: Path) -> None:
        """Persist HyDE embeddings to disk.

        File format: {"model": <name>, "embeddings": {ml_id: [[...], [...]]}}.
        Safe to ship in-repo — embeddings are deterministic per model version.
        """
        if not self._hyde_embeddings:
            raise RuntimeError("No embeddings to save — build the index first.")
        payload = {
            "embeddings": self._hyde_embeddings,
        }
        with open(path, "w") as f:
            json.dump(payload, f)

    def load_index(self, path: Path) -> None:
        """Load HyDE embeddings previously saved via save_index()."""
        with open(path) as f:
            payload = json.load(f)
        self._hyde_embeddings = payload["embeddings"]

    def find_matches(
        self,
        query_embedding: list[float],
        user_grade: Optional[str] = None,
        top_k: int = 5,
    ) -> list[LibraryMatch]:
        """Return top-K library matches ranked by HyDE-similarity.

        Filters:
          - entries with no HyDE embeddings are skipped
        Returns LibraryMatch objects with grade_compatible flag set.
        Caller decides how to use confidence + grade_compatible (per Phase 7 rules).
        """
        if not self._hyde_embeddings:
            raise RuntimeError(
                "MLLibrary index not built. Call build_index_sync/async first."
            )

        scored: list[LibraryMatch] = []
        for entry in self.entries:
            embeddings = self._hyde_embeddings.get(entry.ml_id) or []
            if not embeddings:
                continue

            # Score against each HyDE, keep the best
            best_sim = -1.0
            best_hyde = ""
            for hyde, vec in zip(entry.hyde_summaries, embeddings):
                sim = cosine_similarity(query_embedding, vec)
                if sim > best_sim:
                    best_sim = sim
                    best_hyde = hyde

            scored.append(
                LibraryMatch(
                    entry=entry,
                    confidence=best_sim,
                    matched_hyde=best_hyde,
                    grade_compatible=is_grade_compatible(entry.grade_levels, user_grade),
                )
            )

        scored.sort(key=lambda m: m.confidence, reverse=True)
        return scored[:top_k]

    def find_best_in_grade(
        self,
        query_embedding: list[float],
        user_grade: Optional[str] = None,
        top_k: int = 5,
    ) -> list[LibraryMatch]:
        """Return top-K in-grade matches only (drops grade-incompatible entries)."""
        all_matches = self.find_matches(query_embedding, user_grade, top_k=top_k * 3)
        compatible = [m for m in all_matches if m.grade_compatible]
        return compatible[:top_k]

    def get(self, ml_id: str) -> Optional[LibraryEntry]:
        """O(n) lookup by ml_id. Fine for 183 entries; memoize if it hurts."""
        for e in self.entries:
            if e.ml_id == ml_id:
                return e
        return None


# ---------------------------------------------------------------------------
# Singleton accessor for app startup
# ---------------------------------------------------------------------------


_LIBRARY: Optional[MLLibrary] = None


def get_library() -> MLLibrary:
    """Load scripted_ml_library.json + prebuilt embeddings on first call.

    Raises FileNotFoundError if data/ml_library_embeddings.json is missing —
    the app shouldn't start without a ready index. Run
    `python3 scripts/build_ml_library_index.py` to generate it.
    """
    global _LIBRARY
    if _LIBRARY is None:
        lib = MLLibrary.load()
        if not DEFAULT_INDEX_PATH.exists():
            raise FileNotFoundError(
                f"ML library embedding index not found at {DEFAULT_INDEX_PATH}. "
                "Run: python3 scripts/build_ml_library_index.py"
            )
        lib.load_index(DEFAULT_INDEX_PATH)
        logger.info(
            "MLLibrary loaded: %d entries, embeddings for %d",
            lib.size,
            sum(1 for e in lib.entries if lib._hyde_embeddings.get(e.ml_id)),
        )
        _LIBRARY = lib
    return _LIBRARY
