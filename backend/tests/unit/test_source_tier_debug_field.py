"""Campaign Task 2 — expose per-chunk ``source_tier`` end-to-end.

``source_tier`` is set on the reranked ``RetrievedChunk`` and drives the
assembler's Launch-first ``(source_tier, -score)`` ordering, but it was
dropped the moment a chunk was reduced to a lightweight ``ChunkRef`` for
grounding — so it never reached the ``/api/chat`` ``sources[]`` envelope.

These tests lock the thread-through at each hop:
  ChunkRef.source_tier  ->  _chunk_to_ref copies it  ->  SourceInfo carries it.
"""

from __future__ import annotations

from types import SimpleNamespace

from api.models import SourceInfo
from handlers._retrieval import _chunk_to_ref
from schemas import ChunkRef


def test_sourceinfo_carries_source_tier() -> None:
    info = SourceInfo(
        chunk_id="c1",
        source_document="Launch K-2",
        content_type="lesson",
        relevance_score=0.0,
        source_tier=4,
    )
    assert info.source_tier == 4
    assert "source_tier" in info.model_dump()


def test_sourceinfo_source_tier_defaults_to_none() -> None:
    info = SourceInfo(
        chunk_id="c1",
        source_document="d",
        content_type="",
        relevance_score=0.0,
    )
    assert info.source_tier is None
    assert "source_tier" in info.model_dump()


def test_chunkref_carries_source_tier() -> None:
    ref = ChunkRef(chunk_id="c1", source_document="d", source_tier=4)
    assert ref.source_tier == 4


def test_chunkref_source_tier_defaults_to_none() -> None:
    ref = ChunkRef(chunk_id="c1", source_document="d")
    assert ref.source_tier is None


def test_chunk_to_ref_copies_source_tier() -> None:
    chunk = SimpleNamespace(
        chunk_id="c1",
        source_document="Launch K-2",
        page_number=7,
        source_tier=4,
    )
    ref = _chunk_to_ref(chunk)
    assert ref.chunk_id == "c1"
    assert ref.source_document == "Launch K-2"
    assert ref.page_number == 7
    assert ref.source_tier == 4


def test_chunk_to_ref_defaults_source_tier_when_absent() -> None:
    chunk = SimpleNamespace(chunk_id="c1", source_document="d", page_number=None)
    ref = _chunk_to_ref(chunk)
    assert ref.source_tier is None
