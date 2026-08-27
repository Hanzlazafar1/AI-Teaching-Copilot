"""Common retrieval helpers shared by handlers.

Every handler that needs retrieval calls ``run_retrieval`` with the
TurnIntent; this function builds the hybrid_search kwargs from intent
fields (grade, mode, trait, skill, required_triggers) and returns the
chunks that went INTO the prompt, the formatted context string, and the
grounding refs.

No session-state fallback — the intent is the single source. If intent
lacks a field, retrieval runs without that filter.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from schemas import ChunkRef, TurnIntent

logger = logging.getLogger(__name__)


async def run_retrieval(
    *,
    intent: TurnIntent,
    query_text: str,
    query_type_label: str,
    retrieval_fn: Optional[Callable[..., Awaitable[list[Any]]]],
) -> tuple[list[Any], str, list[ChunkRef]]:
    """Run retrieval with params derived from intent.

    Returns (context_chunks, formatted_context, grounding_refs).
    If retrieval_fn is None, returns empty results.

    ``context_chunks`` is what the model SAW — the chunks that went into
    ``formatted_context`` — NOT the raw list retrieval returned. The assembler
    dedupes by chunk_id, re-orders by (source_tier, -score) and truncates to a
    token budget, so the two lists genuinely differ. The distinction is
    load-bearing for citation: a citation resolves the ``Source:`` id the
    generator NAMED, and the only ids it could name are the ones in the context
    block. ``resolve_attribution`` returns on the FIRST id match, so resolving
    against the raw list would be wrong in both directions — a page-less
    duplicate that never reached the prompt could silence a citeable citation,
    and a chunk truncated out of the budget could be "resolved" to a page the
    model never had in front of it. (Same reasoning, same words, as the sibling
    ``scripted_ml._assemble_for_prompt``; the two paths agree by construction.)

    ``grounding_refs`` stays derived from the RAW list, deliberately: grounding
    answers "what did retrieval find" (provenance/observability) while the
    citation answers "what could the model have named". Different questions,
    different lists — and ``scripted_ml.py`` draws exactly the same line
    (grounding off ``chunks``, citation off ``context_chunks``).

    query_type_label drives the retrieval reranker priority:
      "SCRIPTED_ML", "HOW_TO_TEACH", "PLAN_UNIT", "COACHING_GENERAL",
      "MANAGEMENT", "THINK_ALOUD", "TRIGGER_SPECIFIC".
    """
    if retrieval_fn is None:
        return [], "", []

    kwargs: dict[str, Any] = {
        "query": query_text,
        "intent": _intent_for_retrieval(query_type_label),
        "query_type": query_type_label,
    }
    if intent.skill is not None:
        kwargs["strategy_name"] = intent.skill.canonical
    if intent.grade is not None:
        kwargs["grade_level"] = intent.grade.value
    if intent.mode is not None:
        kwargs["writing_mode"] = intent.mode.value
    if intent.trait is not None:
        kwargs["writing_trait"] = intent.trait.value

    try:
        chunks = await retrieval_fn(**kwargs)
    except TypeError:
        logger.warning(
            "retrieval_fn signature rejected kwargs; retrying with only query"
        )
        chunks = await retrieval_fn(query=query_text)

    formatted, context_chunks = _assemble_for_prompt(chunks)
    # Grounding off the RAW list — see the docstring: provenance is a different
    # question from "what could the model have named".
    grounding = [_chunk_to_ref(c) for c in chunks]
    return context_chunks, formatted, grounding


def _intent_for_retrieval(query_type_label: str) -> str:
    """Map request_type to v3's hybrid_search `intent` param.

    hybrid_search uses "mini_lesson" / "coaching" buckets to pick the
    default top_k and apply copilot_mode filters. Lesson-shaped
    request_types (full scripted lesson, priority-skill plan, think-
    aloud monologue) all want the larger lesson top_k because they
    need enough chunks to cover a full teaching move."""
    lesson_types = {"SCRIPTED_ML", "PLAN_UNIT", "THINK_ALOUD"}
    return "mini_lesson" if query_type_label in lesson_types else "coaching"


def _assemble_for_prompt(chunks: list[Any]) -> tuple[str, list[Any]]:
    """Build the prompt's retrieved-context block AND return the chunks that
    actually went INTO it. Prefer v3's assembler.

    Both halves are returned because they are not interchangeable, and the
    citation depends on the difference — see ``run_retrieval``'s docstring for
    the full argument.

    (Widened from the old ``_format_chunks``, which computed both halves and
    discarded the second — the identical defect plan (1) found and fixed in
    ``scripted_ml._format_chunks_for_prompt``. Renamed with it, and onto that
    sibling's name: a same-named function that silently starts returning a tuple
    breaks its callers at a distance, whereas a rename breaks them at the import
    line.)

    The ImportError fallback fails SAFE rather than correct: it labels each
    block ``Source: <source_document>``, not ``Source: <chunk_id>``, so a model
    on that path can only ever name a document name — which matches no chunk_id
    and therefore resolves to silence. Silence is the right failure here, and
    the branch is unreachable in practice (retrieval.assembler is in-package).
    """
    if not chunks:
        return "", []
    try:
        from retrieval.assembler import assemble_context
        return assemble_context(chunks)
    except ImportError:
        included = list(chunks[:8])
        parts: list[str] = []
        for i, c in enumerate(included, start=1):
            header = f"[{i}] Source: {getattr(c, 'source_document', 'unknown')}"
            page = getattr(c, "page_number", None)
            if page:
                header += f" | Page: {page}"
            parts.append(header + "\n" + getattr(c, "content", ""))
        return "\n\n".join(parts), included


def _chunk_to_ref(chunk: Any) -> ChunkRef:
    return ChunkRef(
        chunk_id=getattr(chunk, "chunk_id", ""),
        source_document=getattr(chunk, "source_document", ""),
        page_number=getattr(chunk, "page_number", None),
        source_tier=getattr(chunk, "source_tier", None),
    )
