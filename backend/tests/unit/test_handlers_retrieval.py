"""Tests for handlers._retrieval — the shared retrieval helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from handlers._retrieval import _intent_for_retrieval, run_retrieval
from retrieval.search import _UNRANKED_SOURCE_TIER
from schemas import (
    GradeSpec,
    ModeSpec,
    RequestType,
    SkillSpec,
    TraitSpec,
    TurnIntent,
)


@dataclass
class _FakeChunk:
    """Shape that satisfies both the grounding extractor and
    retrieval.assembler.assemble_context."""

    chunk_id: str
    source_document: str
    page_number: int | None
    content: str = "body"
    content_type: str = "passage"
    tier: int = 2
    score: float = 1.0
    book_name: str = ""
    grade_level: str = ""
    writing_trait: str = "all"
    writing_mode: str = "all"
    source_tier: int = _UNRANKED_SOURCE_TIER


def _intent() -> TurnIntent:
    return TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        grade=GradeSpec(value="3", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        trait=TraitSpec(value="Ideas", stated_explicit=False, confidence=0.8),
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
    )


@pytest.mark.asyncio
async def test_run_retr_returns_empty_when_fn_is_none() -> None:
    chunks, ctx, grounding = await run_retrieval(
        intent=_intent(),
        query_text="hi",
        query_type_label="HOW_TO_TEACH",
        retrieval_fn=None,
    )
    assert chunks == []
    assert ctx == ""
    assert grounding == []


@pytest.mark.asyncio
async def test_run_retr_threads_intent_fields_to_fn() -> None:
    recorded: dict[str, Any] = {}

    async def _fn(**kwargs: Any) -> list[Any]:
        recorded.update(kwargs)
        return [_FakeChunk(chunk_id="c1", source_document="lww312", page_number=64)]

    _, _, grounding = await run_retrieval(
        intent=_intent(),
        query_text="how do I teach topic sentences?",
        query_type_label="HOW_TO_TEACH",
        retrieval_fn=_fn,
    )
    assert recorded["query"] == "how do I teach topic sentences?"
    assert recorded["query_type"] == "HOW_TO_TEACH"
    assert recorded["strategy_name"] == "topic sentences"
    assert recorded["grade_level"] == "3"
    assert recorded["writing_mode"] == "Inform"
    assert recorded["writing_trait"] == "Ideas"
    assert len(grounding) == 1
    assert grounding[0].chunk_id == "c1"
    assert grounding[0].page_number == 64


@pytest.mark.asyncio
async def test_run_retr_omits_none_intent_fields() -> None:
    recorded: dict[str, Any] = {}

    async def _fn(**kwargs: Any) -> list[Any]:
        recorded.update(kwargs)
        return []

    bare = TurnIntent(request_type=RequestType.COACHING)
    await run_retrieval(
        intent=bare,
        query_text="q",
        query_type_label="COACHING_GENERAL",
        retrieval_fn=_fn,
    )
    assert "grade_level" not in recorded
    assert "writing_mode" not in recorded
    assert "writing_trait" not in recorded
    assert "strategy_name" not in recorded


@pytest.mark.asyncio
async def test_run_retr_falls_back_when_fn_rejects_kwargs() -> None:
    async def _old_fn(query: str) -> list[Any]:
        assert query == "q"
        return [_FakeChunk(chunk_id="c9", source_document="x", page_number=None)]

    _, _, grounding = await run_retrieval(
        intent=_intent(),
        query_text="q",
        query_type_label="HOW_TO_TEACH",
        retrieval_fn=_old_fn,  # type: ignore[arg-type]
    )
    assert len(grounding) == 1
    assert grounding[0].chunk_id == "c9"


# ---------------------------------------------------------------------------
# The first return value is what the model SAW, not the raw list
# ---------------------------------------------------------------------------
#
# ``_format_chunks`` computed ``assemble_context``'s (context, included) and
# threw ``included`` away, so ``run_retrieval`` handed back the RAW list — the
# identical defect plan (1) found in ``scripted_ml._format_chunks_for_prompt``.
# It matters because a citation resolves the ``Source:`` id the generator NAMED,
# and ``resolve_attribution`` returns on the FIRST id match: a duplicate that
# never reached the prompt could silence a citeable citation, and a chunk
# truncated out of the budget could be "resolved" to a page the model never saw.


@pytest.mark.asyncio
async def test_run_retr_returns_the_chunks_the_model_saw_not_the_raw_list() -> None:
    """Kills the revert (``return chunks, ...``): the assembler DEDUPES by
    chunk_id, so a raw list carrying the same id twice assembles to ONE chunk.
    Non-vacuous in both directions — the raw list really has 2 entries (grounding
    proves it), and the context block really carries 1."""

    async def _fn(**kwargs: Any) -> list[Any]:
        return [
            _FakeChunk(chunk_id="dup", source_document="Launching the Writers Workshop 3-12.pdf", page_number=64),
            _FakeChunk(chunk_id="dup", source_document="Launching the Writers Workshop 3-12.pdf", page_number=64),
        ]

    context_chunks, ctx, grounding = await run_retrieval(
        intent=_intent(),
        query_text="q",
        query_type_label="HOW_TO_TEACH",
        retrieval_fn=_fn,
    )
    assert [c.chunk_id for c in context_chunks] == ["dup"], (
        "run_retrieval returned the RAW list — the assembler's deduped "
        "`included` is what the model saw"
    )
    # The block the model read carries exactly the chunks handed back.
    assert ctx.count("Source: dup") == 1
    # Grounding stays RAW, deliberately (provenance != what the model could name).
    assert [g.chunk_id for g in grounding] == ["dup", "dup"]


@pytest.mark.asyncio
async def test_run_retr_returns_chunks_in_the_order_the_model_read_them() -> None:
    """The assembler re-orders by (source_tier, -score) — Launch-first. The
    returned list must carry THAT order, not retrieval's. Kills a fix that
    dedupes but hands back the raw sequence."""

    async def _fn(**kwargs: Any) -> list[Any]:
        return [
            _FakeChunk(chunk_id="second", source_document="x", page_number=1, source_tier=5),
            _FakeChunk(chunk_id="first", source_document="y", page_number=2, source_tier=0),
        ]

    context_chunks, ctx, _ = await run_retrieval(
        intent=_intent(),
        query_text="q",
        query_type_label="HOW_TO_TEACH",
        retrieval_fn=_fn,
    )
    assert [c.chunk_id for c in context_chunks] == ["first", "second"]
    # And that order is the one the model actually read off the block.
    assert ctx.index("Source: first") < ctx.index("Source: second")


def test_intent_for_retr_maps_request_types_to_buckets() -> None:
    assert _intent_for_retrieval("SCRIPTED_ML") == "mini_lesson"
    assert _intent_for_retrieval("PLAN_UNIT") == "mini_lesson"
    assert _intent_for_retrieval("THINK_ALOUD") == "mini_lesson"
    assert _intent_for_retrieval("HOW_TO_TEACH") == "coaching"
    assert _intent_for_retrieval("COACHING_GENERAL") == "coaching"
    assert _intent_for_retrieval("MANAGEMENT") == "coaching"
