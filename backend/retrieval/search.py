"""Hybrid search: dense + sparse + RRF with progressive filter relaxation."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastembed import SparseTextEmbedding
from qdrant_client import AsyncQdrantClient, models

from config import settings
from retrieval.embedder import embed_query
from retrieval.filters import build_filter, relax_filter

logger = logging.getLogger(__name__)

COLLECTION_NAME = "brady_chunks"

_qdrant: AsyncQdrantClient | None = None
_sparse_model: SparseTextEmbedding | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    """Lazy singleton for the async Qdrant client (local in-memory)."""
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(path=settings.qdrant_path)
    return _qdrant


# ---------------------------------------------------------------------------
# Trigger expansion (Section 5.2 step 5): inflate sparse query with synonyms
# of triggers whose related_skills match terms in the user's query. Makes
# "how do I teach paragraphing" pull in pizza-table / table-top chunks.
# ---------------------------------------------------------------------------

_TRIGGERS_PATH = Path(__file__).resolve().parent.parent / "data" / "skill_triggers.json"
_TRIGGERS: dict | None = None


def _load_triggers() -> dict:
    global _TRIGGERS
    if _TRIGGERS is None:
        try:
            _TRIGGERS = json.loads(_TRIGGERS_PATH.read_text()).get("triggers", {})
        except FileNotFoundError:
            logger.warning("skill_triggers.json missing — trigger expansion disabled")
            _TRIGGERS = {}
    return _TRIGGERS


def _normalize_for_match(text: str) -> str:
    """Lower-case, and treat any dash as a space.

    A teacher types "read up write down"; QU canonicalizes it to
    "read-up-write-down". They are the same name and must match the same way.
    """
    return re.sub(r"[-‐-―/]+", " ", (text or "").lower())


def _names_the_trigger(haystack: str, needle: str) -> bool:
    """Is `needle` present in `haystack` as a WHOLE word (or phrase)?

    Word-bounded, never a bare substring: several trigger names are short
    ("pat", "scr", "setting"), and a substring match fires "pat" inside
    "pattern". That is the same bug class as the citation scrubber that
    shipped to a teacher (b5dc2d9), where an unguarded group tore "what page
    2" into "wh". `\\b` is wrong here because names carry punctuation
    ("P.A.T.", "T&T"), so guard on word characters directly.
    """
    n = _normalize_for_match(needle).strip()
    if not n:
        return False
    return re.search(rf"(?<!\w){re.escape(n)}(?!\w)", haystack) is not None


def expand_query_with_triggers(
    query: str, smekens_terms: list[str] | None
) -> tuple[list[str], list[str]]:
    """Return (synonyms, trigger_names) derived from matching triggers.

    A trigger matches when the query or smekens_terms either DESCRIBES its
    skill (`related_skills`) or NAMES it (the canonical key or a `synonyms`
    entry). The trigger names are used downstream to fetch that lesson's
    chunks specifically and to boost them in the reranker.

    Brady's April non-negotiable #7 is about NAMING: "If user names/asks about
    a specific lesson from the book, don't ad lib or make it up. Pull on the
    exact lesson already described in the book." This previously matched
    `related_skills` ONLY — so it fired when a teacher described the skill and
    NOT when they named the strategy, the exact inverse of the rule. Each
    trigger's `synonyms` already held the spoken forms of its name and were
    emitted as output while never being matched against.

    Matching the name from the QUERY TEXT means this no longer depends on QU
    populating `required_triggers` — measured as a coin flip on some phrasings
    (snapple: 1 of 2 identical runs returned []).
    """
    triggers = _load_triggers()
    if not triggers:
        return [], []

    haystack = _normalize_for_match(" ".join([query or ""] + (smekens_terms or [])))
    synonyms: list[str] = []
    trigger_names: list[str] = []
    for trigger_name, data in triggers.items():
        needles = [
            trigger_name,
            *data.get("synonyms", []),
            *data.get("related_skills", []),
        ]
        if any(_names_the_trigger(haystack, n) for n in needles):
            synonyms.extend(data.get("synonyms", []))
            synonyms.append(trigger_name)
            trigger_names.append(trigger_name)
    # Dedupe synonyms preserving order
    seen: set[str] = set()
    syns_unique: list[str] = []
    for t in synonyms:
        if t.lower() not in seen:
            seen.add(t.lower())
            syns_unique.append(t)
    return syns_unique, trigger_names


def get_sparse_model() -> SparseTextEmbedding:
    """Lazy singleton for the BM25 sparse embedding model."""
    global _sparse_model
    if _sparse_model is None:
        _sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _sparse_model


# Non-reranked chunks (hand-built test chunks, ImportError fallback lists) sink
# to the bottom; the assembler's (source_tier, -score) sort then degenerates to
# legacy -score ordering for them. Distinct from the ignored payload `tier`.
_UNRANKED_SOURCE_TIER = 10**9


@dataclass
class RetrievedChunk:
    """A chunk returned from search with its metadata and score.

    Includes Phase 1-3 enrichment fields (book_name, chapter_number,
    pie_tags_by_band, etc.) so Phase 6 priority re-ranking can boost
    by source without a second lookup.
    """
    chunk_id: str
    source_document: str
    content_type: str
    content: str
    grade_level: str
    writing_trait: str
    writing_mode: str
    strategy_name: str
    tier: int
    step: str
    score: float
    # Phase 1-3 enrichment (defaults keep pre-re-ingest chunks working)
    book_name: str | None = None
    chapter_number: int | None = None
    ml_number: int | None = None
    skill_title: str = ""
    pie_tags_by_band: dict = None
    page_number: int | None = None
    book_reference: str | None = None
    lesson_trigger: list = None
    is_scripted_lesson: bool = False
    priority_rank: int | None = None
    source_tier: int = _UNRANKED_SOURCE_TIER

    def __post_init__(self) -> None:
        # Dataclass mutable defaults — coerce to empty dict/list if None.
        if self.pie_tags_by_band is None:
            self.pie_tags_by_band = {}
        if self.lesson_trigger is None:
            self.lesson_trigger = []


def _sparse_encode(text: str) -> models.SparseVector:
    """Encode text into a BM25 sparse vector."""
    model = get_sparse_model()
    embeddings = list(model.query_embed(text))
    emb = embeddings[0]
    return models.SparseVector(
        indices=emb.indices.tolist(),
        values=emb.values.tolist(),
    )


def _point_to_chunk(point: models.ScoredPoint) -> RetrievedChunk:
    """Convert a Qdrant ScoredPoint to a RetrievedChunk."""
    p = point.payload or {}
    return RetrievedChunk(
        chunk_id=p.get("chunk_id", ""),
        source_document=p.get("source_document", ""),
        content_type=p.get("content_type", ""),
        content=p.get("content", ""),
        grade_level=p.get("grade_level", ""),
        writing_trait=p.get("writing_trait", ""),
        writing_mode=p.get("writing_mode", ""),
        strategy_name=p.get("strategy_name", ""),
        tier=p.get("tier", 2),
        step=p.get("step", ""),
        score=point.score or 0.0,
        book_name=p.get("book_name"),
        chapter_number=p.get("chapter_number"),
        ml_number=p.get("ml_number"),
        skill_title=p.get("skill_title", ""),
        pie_tags_by_band=p.get("pie_tags_by_band") or {},
        page_number=p.get("page_number"),
        book_reference=p.get("book_reference"),
        lesson_trigger=p.get("lesson_trigger") or [],
        is_scripted_lesson=p.get("is_scripted_lesson", False),
        priority_rank=p.get("priority_rank"),
    )


async def hybrid_search(
    query: str,
    *,
    intent: str | None = None,
    grade_level: str | None = None,
    writing_mode: str | None = None,
    writing_trait: str | None = None,
    step_focus: str | None = None,
    strategy_name: str | None = None,
    smekens_terms: list[str] | None = None,
    dense_vector: list[float] | None = None,
    top_k: int | None = None,
    query_type: str | None = None,
) -> list[RetrievedChunk]:
    """Run hybrid dense+sparse search with RRF fusion and metadata filtering.

    Args:
        query: The original user query text.
        intent: "mini_lesson" or "coaching" — determines copilot_mode filter.
        grade_level: Specific grade like "3" — expanded to include ranges.
        writing_mode: "Inform", "Persuade", or "Entertain".
        writing_trait: One of the 6+1 traits.
        step_focus: Specific step to filter on.
        strategy_name: Specific Smekens strategy.
        smekens_terms: Expanded terms from query understanding for sparse boost.
        dense_vector: Pre-computed dense embedding (to avoid re-embedding).
        top_k: Number of results. Defaults based on intent.

    Returns:
        List of RetrievedChunk sorted by relevance.
    """
    final_k = top_k if top_k is not None else (
        settings.retrieval_top_k_lesson
        if intent == "mini_lesson"
        else settings.retrieval_top_k_coaching
    )
    # Phase 6: fetch a larger candidate pool so the reranker has headroom.
    # Reranker needs enough headroom to find Launch-book / library-backed
    # chunks even when PIE / Essential Skills / Episode content semantically
    # matches the query more directly. Brady's source-priority rule requires
    # Launch content in top-3 for narrative + K-12 queries (R2-H1); the old
    # candidate_k=max(20, final_k) frequently didn't surface the Launch
    # chunks into the reranker's view at all. 5× the final_k gives the
    # reranker's tier sort enough population to work with.
    candidate_k = max(50, final_k * 5)

    # 1. Dense embedding (use pre-computed if available)
    if dense_vector is None:
        dense_vector = await embed_query(query)

    # 2. Sparse encoding with Smekens term + trigger-synonym expansion.
    # Trigger expansion lets queries like "how do I teach paragraphing" surface
    # table-top / pizza-table chunks even when the user never says "pizza table".
    expansion_syns, expansion_triggers = expand_query_with_triggers(query, smekens_terms)
    sparse_input = query
    if smekens_terms:
        sparse_input = f"{sparse_input} {' '.join(smekens_terms)}"
    if expansion_syns:
        sparse_input = f"{sparse_input} {' '.join(expansion_syns)}"
        logger.debug(
            "Trigger expansion added %d terms, triggers=%s",
            len(expansion_syns), expansion_triggers,
        )
    sparse_vector = _sparse_encode(sparse_input)

    # 3. Build metadata filter. Note: build_filter internally suppresses the
    # writing_trait filter when strategy_name is set (see R02 in
    # FEEDBACK-ISSUES.md) so we don't need to special-case it here.
    metadata_filter = build_filter(
        intent=intent,
        grade_level=grade_level,
        writing_mode=writing_mode,
        writing_trait=writing_trait,
        step_focus=step_focus,
        strategy_name=strategy_name,
    )

    # 4. Run hybrid search with progressive filter relaxation
    client = get_qdrant_client()
    results = await _search_with_relaxation(
        client=client,
        dense_vector=dense_vector,
        sparse_vector=sparse_vector,
        metadata_filter=metadata_filter,
        top_k=candidate_k,
    )

    # 5. Convert to RetrievedChunk objects
    chunks = [_point_to_chunk(r) for r in results]

    # 5a. Supplementary pool: when query expansion matched canonical triggers,
    # hybrid-search the trigger-tagged chunks specifically. The query_points
    # call below ranks them by actual dense+sparse relevance (no synthetic
    # baseline), so weak-semantic matches don't unfairly float up on tag alone.
    if expansion_triggers:
        existing_ids = {c.chunk_id for c in chunks}
        supplement = await _fetch_by_trigger(
            client, expansion_triggers, dense_vector, sparse_vector,
            candidate_k=candidate_k,
            # The SAME filter the main pool ran under. The supplement widens
            # relevance, never the grade band.
            metadata_filter=metadata_filter,
        )
        for s in supplement:
            if s.chunk_id not in existing_ids:
                chunks.append(s)
                existing_ids.add(s.chunk_id)

    # 6. Phase 6 — priority-weighted re-rank, then trim to final_k.
    # Lazy import avoids a circular dependency on RetrievedChunk.
    from retrieval.reranker import rerank as priority_rerank

    chunks = priority_rerank(
        chunks,
        query_type=query_type or "DEFAULT",
        user_grade=grade_level,
        writing_mode=writing_mode,
        top_k=final_k,
        triggered_triggers=expansion_triggers,
    )

    logger.info(
        "Hybrid search: %d results (from %d candidates) for query='%s' "
        "(type=%s, grade=%s, mode=%s, trait=%s)",
        len(chunks),
        candidate_k,
        query[:80],
        query_type,
        grade_level,
        writing_mode,
        writing_trait,
    )

    return chunks


async def _fetch_by_trigger(
    client: AsyncQdrantClient,
    trigger_names: list[str],
    dense_vector: list[float],
    sparse_vector: models.SparseVector,
    candidate_k: int = 50,
    *,
    metadata_filter: Optional[models.Filter],
) -> list[RetrievedChunk]:
    """Hybrid-rank chunks whose `lesson_trigger` contains a matched trigger.

    Runs a *real* dense+sparse+RRF query scoped to trigger-tagged chunks so
    the results carry genuine relevance scores (not a synthetic baseline).
    Used as a supplementary candidate source when the query expanded to a
    known trigger (e.g., "paragraphing" → pizza-table) and the main pool
    may have missed scripted-ML chunks that actually teach the trigger.

    ``metadata_filter`` is the SAME filter the main pool ran under, ANDed with
    the trigger scope. This supplement widens RELEVANCE — it surfaces a
    trigger-tagged lesson the global top-K missed — and must never widen the
    GRADE BAND. It previously took no filter at all, so its results (appended
    straight into the pool by the caller) silently bypassed the grade filter
    Wave 2b shipped (F20/F67); the citation layer then reads a chunk straight
    out of that pool with no band check of its own, turning an out-of-band chunk
    into a CITATION. (Measured against the rank-based picker of the day,
    ``handlers/citation.py::select_citation_source``, since replaced by
    ``resolve_attribution`` — but the pool is still the only place the band is
    enforced, so this filter is what stands between an out-of-band chunk and a
    citation.) Measured: 8 of 245 campaign citations were
    out-of-band — ALL paragraphing/topic-sentence at grades 3-4 citing the K-2
    book, zero from any other family ("pizza-table" is tagged on both books;
    "transitions" has no K-2 chunks and never leaked). Brady cites the 3-12 book
    on that exact query in his own worked example.

    It is REQUIRED and keyword-only ON PURPOSE: a default would let a future
    caller omit it and silently re-open the bypass. ``None`` is legal and means
    "the caller has no filter" — an explicit decision, not an oversight.
    """
    if not trigger_names:
        return []
    trigger_scope = models.Filter(
        should=[
            models.FieldCondition(
                key="lesson_trigger",
                match=models.MatchValue(value=t),
            )
            for t in trigger_names
        ]
    )
    # Nested AND — unambiguous: (metadata) AND (any matched trigger). Merging
    # `should` into a filter that also carries `must` would leave the OR's
    # semantics dependent on Qdrant's must/should interaction.
    flt = (
        models.Filter(must=[metadata_filter, trigger_scope])
        if metadata_filter is not None
        else trigger_scope
    )
    try:
        results = await client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=dense_vector, using="dense",
                    filter=flt, limit=candidate_k,
                ),
                models.Prefetch(
                    query=sparse_vector, using="sparse",
                    filter=flt, limit=candidate_k,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=flt,
            limit=15,
        )
        points = results.points
    except Exception as e:
        logger.warning("trigger-supplement hybrid search failed: %s", e)
        return []
    return [_point_to_chunk(p) for p in points]


async def _search_with_relaxation(
    *,
    client: AsyncQdrantClient,
    dense_vector: list[float],
    sparse_vector: models.SparseVector,
    metadata_filter: models.Filter,
    top_k: int,
) -> list[models.ScoredPoint]:
    """Execute search with progressive filter relaxation if too few results."""
    current_filter = metadata_filter

    for relaxation_step in range(4):  # 0=original, 1-3=relaxation steps
        # Use None instead of empty filter (Qdrant treats them differently)
        effective_filter = current_filter if current_filter.must else None
        results = await client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=dense_vector,
                    using="dense",
                    filter=effective_filter,
                    limit=top_k,
                ),
                models.Prefetch(
                    query=sparse_vector,
                    using="sparse",
                    filter=effective_filter,
                    limit=top_k,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=effective_filter,
            limit=top_k,
        )

        if len(results.points) >= settings.min_results_before_relaxation:
            if relaxation_step > 0:
                logger.info(
                    "Filter relaxation step %d yielded %d results.",
                    relaxation_step,
                    len(results.points),
                )
            return results.points

        # Try relaxing the filter
        if relaxation_step < 3:
            relaxed = relax_filter(current_filter, relaxation_step + 1)
            if relaxed is not None:
                logger.info(
                    "Only %d results, relaxing filter (step %d)...",
                    len(results.points),
                    relaxation_step + 1,
                )
                current_filter = relaxed
            else:
                # Nothing to relax at this step — try next step
                continue
        else:
            return results.points

    return []
