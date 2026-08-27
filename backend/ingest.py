"""Ingestion pipeline: load chunks, embed, store in Qdrant.

Idempotent — deletes and recreates the collection on each run.
Excludes framework chunks (loaded at startup) and textbook chunks (incorrect).

Usage:
    python ingest.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from pathlib import Path

from openai import OpenAI
from qdrant_client import QdrantClient, models
from fastembed import SparseTextEmbedding

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

COLLECTION_NAME = "brady_chunks"

# --- Allowed metadata values (closed sets for validation) ---

VALID_GRADE_LEVELS = frozenset({
    "K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
    "PK-1",
    "K-2", "K-5", "K-12", "3-5", "3-12", "6-8", "6-12", "9-12",
})

VALID_WRITING_TRAITS = frozenset({
    "Ideas", "Organization", "Voice", "Word Choice",
    "Sentence Fluency", "Conventions", "all",
})

VALID_WRITING_MODES = frozenset({
    "Inform", "Persuade", "Entertain", "all",
})

VALID_COPILOT_MODES = frozenset({
    "lesson_generation", "coaching", "both",
})

# Payload fields to index for fast filtering
INDEXED_FIELDS = [
    ("grade_level", models.PayloadSchemaType.KEYWORD),
    ("writing_trait", models.PayloadSchemaType.KEYWORD),
    ("writing_mode", models.PayloadSchemaType.KEYWORD),
    ("copilot_mode", models.PayloadSchemaType.KEYWORD),
    ("content_type", models.PayloadSchemaType.KEYWORD),
    ("step", models.PayloadSchemaType.KEYWORD),
    ("strategy_name", models.PayloadSchemaType.KEYWORD),
    ("tier", models.PayloadSchemaType.INTEGER),
]


def chunk_id_to_point_id(chunk_id: str) -> int:
    """Deterministic int64 point ID from chunk_id string."""
    h = hashlib.sha256(chunk_id.encode()).hexdigest()
    return int(h[:16], 16) & 0x7FFFFFFFFFFFFFFF  # positive int64


def validate_chunk(chunk: dict, filename: str, idx: int) -> list[str]:
    """Validate a single chunk's metadata. Returns list of warnings."""
    warnings = []
    cid = chunk.get("chunk_id", f"{filename}[{idx}]")

    gl = str(chunk.get("grade_level", ""))
    if gl and gl not in VALID_GRADE_LEVELS:
        warnings.append(f"  {cid}: invalid grade_level '{gl}'")

    wt = chunk.get("writing_trait", "")
    if wt and wt not in VALID_WRITING_TRAITS:
        warnings.append(f"  {cid}: invalid writing_trait '{wt}'")

    wm = chunk.get("writing_mode", "")
    if wm and wm not in VALID_WRITING_MODES:
        warnings.append(f"  {cid}: invalid writing_mode '{wm}'")

    cm = chunk.get("copilot_mode", "")
    if cm and cm not in VALID_COPILOT_MODES:
        warnings.append(f"  {cid}: invalid copilot_mode '{cm}'")

    if not chunk.get("content"):
        warnings.append(f"  {cid}: empty content")

    return warnings


def load_chunks() -> list[dict]:
    """Load all chunk JSON files, skipping excluded ones."""
    chunks_dir = Path(settings.chunks_dir)
    exclude = set(settings.ingest_exclude_files)
    all_chunks: list[dict] = []
    all_warnings: list[str] = []

    for filepath in sorted(chunks_dir.glob("*.json")):
        if filepath.name in exclude:
            logger.info("Skipping excluded file: %s", filepath.name)
            continue

        with open(filepath) as f:
            data = json.load(f)

        for i, chunk in enumerate(data):
            warnings = validate_chunk(chunk, filepath.name, i)
            all_warnings.extend(warnings)

        all_chunks.extend(data)
        logger.info("Loaded %s: %d chunks", filepath.name, len(data))

    if all_warnings:
        logger.warning("Validation warnings:\n%s", "\n".join(all_warnings))

    logger.info("Total chunks loaded: %d", len(all_chunks))
    return all_chunks


def embed_chunks(chunks: list[dict], client: OpenAI) -> list[list[float]]:
    """Embed chunk contents using OpenAI text-embedding-3-large in batches."""
    texts = [c["content"] for c in chunks]
    batch_size = 100
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        logger.info(
            "Embedding batch %d/%d (%d chunks)...",
            i // batch_size + 1,
            (len(texts) + batch_size - 1) // batch_size,
            len(batch),
        )
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=batch,
        )
        all_embeddings.extend([d.embedding for d in response.data])

    return all_embeddings


def compute_sparse_vectors(
    chunks: list[dict], sparse_model: SparseTextEmbedding
) -> list[models.SparseVector]:
    """Compute BM25 sparse vectors for all chunks using fastembed."""
    texts = [c["content"] for c in chunks]
    logger.info("Computing sparse BM25 vectors for %d chunks...", len(texts))
    sparse_embeddings = list(sparse_model.embed(texts))

    result = []
    for emb in sparse_embeddings:
        result.append(
            models.SparseVector(
                indices=emb.indices.tolist(),
                values=emb.values.tolist(),
            )
        )
    return result


def build_payload(chunk: dict) -> dict:
    """Extract payload fields from a chunk (all metadata + content).

    Includes Phase 1-3 enrichment fields (book_name, chapter_number,
    pie_tags_by_band, page_number, lesson_trigger, skill_title, etc.)
    so the Phase 6 reranker can boost by source without a second lookup.
    """
    return {
        "chunk_id": chunk.get("chunk_id", ""),
        "source_document": chunk.get("source_document", ""),
        "tier": chunk.get("tier", 2),
        "content_type": chunk.get("content_type", ""),
        "source_category": chunk.get("source_category", ""),
        "copilot_mode": chunk.get("copilot_mode", ""),
        "step": chunk.get("step", ""),
        "grade_level": str(chunk.get("grade_level", "")),
        "writing_trait": chunk.get("writing_trait", ""),
        "writing_mode": chunk.get("writing_mode", ""),
        "strategy_name": chunk.get("strategy_name", ""),
        "is_scripted_example": chunk.get("is_scripted_example", False),
        "audience": chunk.get("audience", ""),
        "section_name": chunk.get("section_name", ""),
        "day_number": chunk.get("day_number"),
        "episode_number": chunk.get("episode_number"),
        "content": chunk.get("content", ""),
        # --- Phase 1-3 enrichment (used by Phase 6 priority reranker) ---
        "book_name": chunk.get("book_name"),
        "chapter_number": chunk.get("chapter_number"),
        "ml_number": chunk.get("ml_number"),
        "skill_title": chunk.get("skill_title", ""),
        "pie_tags_by_band": chunk.get("pie_tags_by_band") or {},
        "page_number": chunk.get("page_number"),
        "book_reference": chunk.get("book_reference"),
        "lesson_trigger": chunk.get("lesson_trigger") or [],
        "is_scripted_lesson": chunk.get("is_scripted_lesson", False),
        "priority_rank": chunk.get("priority_rank"),
        "topic_keywords": chunk.get("topic_keywords") or [],
    }


def create_collection(qdrant: QdrantClient) -> None:
    """Delete (if exists) and recreate the collection with proper config."""
    if qdrant.collection_exists(COLLECTION_NAME):
        logger.info("Deleting existing collection '%s'...", COLLECTION_NAME)
        qdrant.delete_collection(COLLECTION_NAME)

    logger.info("Creating collection '%s'...", COLLECTION_NAME)
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": models.VectorParams(
                size=settings.embedding_dimensions,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(),
        },
    )

    # Create payload indexes for fast filtering
    for field_name, field_type in INDEXED_FIELDS:
        qdrant.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field_name,
            field_schema=field_type,
        )
    logger.info("Created %d payload indexes.", len(INDEXED_FIELDS))


def upsert_points(
    qdrant: QdrantClient,
    chunks: list[dict],
    dense_embeddings: list[list[float]],
    sparse_vectors: list[models.SparseVector],
) -> None:
    """Upsert all points into the collection in batches."""
    batch_size = 100

    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i : i + batch_size]
        batch_dense = dense_embeddings[i : i + batch_size]
        batch_sparse = sparse_vectors[i : i + batch_size]

        points = []
        for chunk, dense_vec, sparse_vec in zip(
            batch_chunks, batch_dense, batch_sparse
        ):
            point_id = chunk_id_to_point_id(chunk["chunk_id"])
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={
                        "dense": dense_vec,
                        "sparse": sparse_vec,
                    },
                    payload=build_payload(chunk),
                )
            )

        qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
        logger.info(
            "Upserted batch %d/%d (%d points)",
            i // batch_size + 1,
            (len(chunks) + batch_size - 1) // batch_size,
            len(points),
        )


def main() -> None:
    start = time.time()

    # 1. Load chunks
    chunks = load_chunks()
    if not chunks:
        logger.error("No chunks loaded. Check chunks directory.")
        sys.exit(1)

    # 2. Initialize clients
    openai_kwargs = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        openai_kwargs["base_url"] = settings.openai_base_url
    openai_client = OpenAI(**openai_kwargs)
    qdrant_client = QdrantClient(path=settings.qdrant_path)
    sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

    # 3. Embed chunks (dense)
    dense_embeddings = embed_chunks(chunks, openai_client)

    # 4. Compute sparse vectors (BM25)
    sparse_vectors = compute_sparse_vectors(chunks, sparse_model)

    # 5. Create collection
    create_collection(qdrant_client)

    # 6. Upsert points
    upsert_points(qdrant_client, chunks, dense_embeddings, sparse_vectors)

    elapsed = time.time() - start
    info = qdrant_client.get_collection(COLLECTION_NAME)
    logger.info(
        "Ingestion complete: %d points in %.1fs. Collection: %s",
        info.points_count,
        elapsed,
        COLLECTION_NAME,
    )


if __name__ == "__main__":
    main()
