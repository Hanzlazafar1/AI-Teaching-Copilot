"""Double-rerank fix: retrieval_fn must not re-run rerank on hybrid_search's
already-boosted output (which squared the boost: base * boost**2)."""
import pytest

from api import dependencies
from retrieval.search import RetrievedChunk


def _launch_chunk(score: float) -> RetrievedChunk:
    # A Launch scripted ML matching mode → priority_boost = 1.5 (would be
    # re-applied by a second rerank). If retrieval_fn reranks again, score
    # becomes score * 1.5; the fix leaves it untouched.
    return RetrievedChunk(
        chunk_id="c", source_document="", content_type="", content="",
        grade_level="", writing_trait="", writing_mode="Inform",
        strategy_name="", tier=2, step="", score=score,
        book_name="Teal", is_scripted_lesson=True,
    )


@pytest.mark.asyncio
async def test_retrieval_fn_does_not_double_boost(monkeypatch):
    already_boosted = _launch_chunk(0.9)

    async def fake_hybrid_search(**kwargs):
        return [already_boosted]

    monkeypatch.setattr(dependencies, "hybrid_search", fake_hybrid_search)

    out = await dependencies.retrieval_fn(
        query="x", intent="mini_lesson", query_type="SCRIPTED_ML",
        grade_level="4", writing_mode="Inform",
    )
    assert out[0].score == pytest.approx(0.9)  # NOT 0.9 * 1.5
