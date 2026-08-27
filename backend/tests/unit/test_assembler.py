"""Tests for retrieval/assembler.py — context assembly, ordering, dedup, budget."""

from retrieval.assembler import assemble_context
from retrieval.search import RetrievedChunk


def _make_chunk(
    chunk_id: str = "test-chunk",
    content_type: str = "episode_explanation",
    content: str = "Test content.",
    tier: int = 2,
    score: float = 0.5,
    **kwargs,
) -> RetrievedChunk:
    defaults = dict(
        source_document="test.pdf",
        grade_level="K-5",
        writing_trait="Ideas",
        writing_mode="Inform",
        strategy_name="",
        step="",
    )
    defaults.update(kwargs)
    return RetrievedChunk(
        chunk_id=chunk_id,
        content_type=content_type,
        content=content,
        tier=tier,
        score=score,
        **defaults,
    )


class TestAssembleContext:
    """Verify context assembly logic."""

    def test_empty_chunks(self):
        ctx, included = assemble_context([])
        assert ctx == ""
        assert included == []

    def test_single_chunk(self):
        chunks = [_make_chunk(content="Hello world.")]
        ctx, included = assemble_context(chunks)
        assert "Hello world." in ctx
        assert len(included) == 1
        assert "RETRIEVED CONTEXT" in ctx
        assert "END CONTEXT" in ctx

    def test_deduplication_keeps_highest_score(self):
        chunks = [
            _make_chunk(chunk_id="dup-1", score=0.5, content="Low score."),
            _make_chunk(chunk_id="dup-1", score=0.9, content="High score."),
        ]
        ctx, included = assemble_context(chunks)
        assert len(included) == 1
        assert "High score." in ctx

    def test_ordering_is_score_only(self):
        """Phase 6+: the reranker is authoritative. The assembler no longer
        has a content-type priority table — it sorts purely by the post-boost
        score supplied by the reranker. Callers that want lesson_script to
        outrank episode_explanation must arrange that via the reranker."""
        chunks = [
            _make_chunk(
                chunk_id="ep-1",
                content_type="episode_explanation",
                score=0.9,  # higher score (as if reranker boosted it)
                content="Episode content.",
            ),
            _make_chunk(
                chunk_id="ls-1",
                content_type="lesson_script",
                score=0.5,
                content="Lesson script content.",
            ),
        ]
        ctx, included = assemble_context(chunks)
        ep_pos = ctx.index("Episode content.")
        ls_pos = ctx.index("Lesson script content.")
        # Higher score wins, regardless of content_type.
        assert ep_pos < ls_pos

    def test_tier_boost_now_noop(self):
        """Historical tier-1 multiplier is a no-op now; the Phase 6 priority
        reranker is authoritative about which chunks rise. Both tiers sort by
        raw score within the same content_type priority."""
        chunks = [
            _make_chunk(
                chunk_id="t2",
                content_type="episode_explanation",
                tier=2,
                score=0.8,
                content="Tier 2 content.",
            ),
            _make_chunk(
                chunk_id="t1",
                content_type="episode_explanation",
                tier=1,
                score=0.7,
                content="Tier 1 content.",
            ),
        ]
        ctx, included = assemble_context(chunks)
        # Same content_type priority → sort by score descending. Tier is ignored.
        t2_pos = ctx.index("Tier 2 content.")
        t1_pos = ctx.index("Tier 1 content.")
        assert t2_pos < t1_pos

    def test_source_header_format(self):
        chunks = [
            _make_chunk(
                chunk_id="skill1-test",
                content_type="lesson_script",
                grade_level="3",
                writing_trait="Organization",
                writing_mode="Inform",
            ),
        ]
        ctx, _ = assemble_context(chunks)
        assert "Source: skill1-test" in ctx
        assert "Type: lesson_script" in ctx
        assert "Grade: 3" in ctx
        assert "Trait: Organization" in ctx

    def test_token_budget_enforcement(self, monkeypatch):
        """Chunks exceeding token budget should be dropped."""
        # Set a very small budget
        monkeypatch.setattr("retrieval.assembler.settings.context_token_budget", 100)

        long_content = "word " * 200  # ~200 tokens
        chunks = [
            _make_chunk(chunk_id="c1", content="Short content.", score=0.9),
            _make_chunk(chunk_id="c2", content=long_content, score=0.5),
        ]
        ctx, included = assemble_context(chunks)
        # Should include c1 but skip c2
        assert len(included) == 1
        assert included[0].chunk_id == "c1"

    def test_orders_by_source_tier_then_score(self):
        """F18: a low-scoring tier-0 chunk must lead a high-scoring tier-2 chunk
        in the assembled context string (assembler reproduces reranker order)."""
        launch = _make_chunk(chunk_id="launch", source_tier=0, score=0.4,
                             content="Launch content.")
        other = _make_chunk(chunk_id="other", source_tier=2, score=0.9,
                            content="Other content.")
        ctx, included = assemble_context([other, launch])
        assert included[0].chunk_id == "launch"
        assert ctx.index("Launch content.") < ctx.index("Other content.")

    def test_unranked_chunk_sinks_to_bottom(self):
        """A chunk that never went through rerank (sentinel source_tier) sorts
        last, never above a reranked chunk."""
        ranked = _make_chunk(chunk_id="ranked", source_tier=1, score=0.3,
                            content="Ranked content.")
        unranked = _make_chunk(chunk_id="unranked", score=0.99,
                              content="Unranked content.")  # default sentinel tier
        ctx, included = assemble_context([unranked, ranked])
        assert included[0].chunk_id == "ranked"

    def test_tier0_survives_budget_truncation(self):
        """F18: tier ordering lets a tier-0 chunk both LEAD and SURVIVE
        truncation while a higher-SCORING tier-2 chunk is dropped. Sizes are
        tuned (verified with tiktoken) so the filler FITS ALONE (~9378 tok +
        ~17 overhead < 10000) but NOT alongside launch (~628 + ~9378 + ~17 =
        ~10023 > 10000): under the OLD score-only sort the high-score filler
        was placed first and consumed the budget, DROPPING the tier-0 launch;
        under (source_tier, -score) the launch leads and the filler is dropped."""
        from config import settings
        assert settings.context_token_budget == 10000  # sizes below assume this
        launch = _make_chunk(chunk_id="launch", content_type="episode_explanation",
                            source_tier=0, score=0.4, content="word " * 600)
        filler = _make_chunk(chunk_id="filler", content_type="episode_explanation",
                            source_tier=2, score=0.9, content="word " * 9350)
        ctx, included = assemble_context([filler, launch])
        assert [c.chunk_id for c in included] == ["launch"]  # tier-0 leads AND survives
        assert all(c.chunk_id != "filler" for c in included)  # higher-score tier-2 dropped
