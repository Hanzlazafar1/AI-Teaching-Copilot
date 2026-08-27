"""Context assembly: order, deduplicate, and format retrieved chunks for the LLM.

Framework chunks are NOT handled here — they are loaded at startup
and baked into the system prompt. This module only assembles search results.
"""

from __future__ import annotations

import logging

import tiktoken

from config import settings
from retrieval.search import RetrievedChunk

logger = logging.getLogger(__name__)

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Lazy singleton for the tiktoken encoder (GPT-4o tokenizer)."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.encoding_for_model("gpt-4o")
    return _encoder


def _count_tokens(text: str) -> int:
    """Count tokens in a string using the GPT-4o tokenizer."""
    return len(_get_encoder().encode(text))


# Map the internal short-code book_name stored on each chunk to the
# full teacher-facing title that responses should cite. Brady's teachers
# recognize "Launching the Writers Workshop 3-12" from their shelves;
# the internal "Teal" / "K-2" shorthand is Smekens jargon. We never
# want shorthand to appear in responses — the full title always wins.
_BOOK_FULL_TITLE = {
    "Teal": "Launching the Writers Workshop 3-12",
    "K-2":  "Launching the Writers Workshop K-2",
}


def _full_book_title(chunk: RetrievedChunk) -> str | None:
    """Resolve the teacher-facing full title for a Launch book chunk.

    Prefers the ``book_name`` → full-title map. Falls back to stripping
    a ``.pdf`` suffix off ``source_document`` for chunks whose
    ``book_name`` wasn't populated but whose document name contains the
    full title already (e.g., "Launching the Writers Workshop 3-12.pdf").
    Returns None for non-Launch chunks (episodes, essential skills, etc.)
    so the header stays uncluttered on content that wouldn't be cited."""
    mapped = _BOOK_FULL_TITLE.get(chunk.book_name or "")
    if mapped:
        return mapped
    src = chunk.source_document or ""
    if src.startswith("Launching the Writers Workshop"):
        return src[:-4] if src.lower().endswith(".pdf") else src
    return None


def _format_chunk(index: int, chunk: RetrievedChunk) -> str:
    """Format a single chunk with its source header.

    The header exposes:

      * ``Source: <chunk_id>`` — canonical chunk ID.
      * ``Book: <full-title>`` — teacher-facing book title when the chunk
        is from a Launch book. Responses cite this title verbatim; never
        the internal shorthand "Teal" / "K-2".
      * ``Page: <N>`` — the chunk's page number when known. Validators
        and the scrubber use this to confirm cited pages match reality.

    The title + page exposure is what makes trustable citation possible:
    the generator cites ONLY what it sees here, and the validator can
    regex-match the response against these headers to catch any invention.
    """
    header_parts = [f"Source: {chunk.chunk_id}"]
    if chunk.content_type:
        header_parts.append(f"Type: {chunk.content_type}")
    if chunk.grade_level:
        header_parts.append(f"Grade: {chunk.grade_level}")
    if chunk.writing_trait and chunk.writing_trait != "all":
        header_parts.append(f"Trait: {chunk.writing_trait}")
    if chunk.writing_mode and chunk.writing_mode != "all":
        header_parts.append(f"Mode: {chunk.writing_mode}")
    book_title = _full_book_title(chunk)
    if book_title:
        header_parts.append(f"Book: {book_title}")
    if chunk.page_number is not None:
        header_parts.append(f"Page: {chunk.page_number}")

    header = f"[{index}] {' | '.join(header_parts)}"
    return f"{header}\n{chunk.content}"


def assemble_context(chunks: list[RetrievedChunk]) -> tuple[str, list[RetrievedChunk]]:
    """Assemble retrieved chunks into a formatted context string.

    Deduplicates, orders by the reranker's (source_tier, -score) — Launch-
    first, ties broken by boosted score — and enforces the token budget.

    Args:
        chunks: Retrieved chunks from hybrid search.

    Returns:
        Tuple of (formatted context string, list of included chunks).
    """
    if not chunks:
        return "", []

    # 1. Deduplicate by chunk_id (keep the better (source_tier, -score))
    seen: dict[str, RetrievedChunk] = {}
    for chunk in chunks:
        existing = seen.get(chunk.chunk_id)
        if existing is None or (chunk.source_tier, -chunk.score) < (existing.source_tier, -existing.score):
            seen[chunk.chunk_id] = chunk
    deduped = list(seen.values())

    # 2. Reproduce the reranker's own (tier, boosted-score) order; the reranker
    # is authoritative and `score` already carries its multiplicative boost.
    deduped.sort(key=lambda c: (c.source_tier, -c.score))

    # 3. Assemble within token budget
    budget = settings.context_token_budget
    parts: list[str] = []
    included: list[RetrievedChunk] = []
    used_tokens = 0

    # Header/footer overhead
    header = "=== RETRIEVED CONTEXT ==="
    footer = "=== END CONTEXT ==="
    overhead = _count_tokens(header) + _count_tokens(footer) + 4  # newlines
    used_tokens += overhead

    for i, chunk in enumerate(deduped):
        formatted = _format_chunk(i + 1, chunk)
        chunk_tokens = _count_tokens(formatted)

        # Always include lesson_scripts and think_aloud_guides if possible
        is_priority = chunk.content_type in ("lesson_script", "think_aloud_guide")

        if used_tokens + chunk_tokens > budget and not is_priority:
            logger.debug(
                "Token budget reached (%d/%d), skipping %s",
                used_tokens,
                budget,
                chunk.chunk_id,
            )
            continue

        if used_tokens + chunk_tokens > budget and is_priority:
            # Even priority chunks must respect a hard ceiling (budget + 50%)
            if used_tokens + chunk_tokens > budget * 1.5:
                logger.debug(
                    "Hard ceiling reached, skipping priority chunk %s",
                    chunk.chunk_id,
                )
                continue

        parts.append(formatted)
        included.append(chunk)
        used_tokens += chunk_tokens

    context = f"{header}\n\n" + "\n\n".join(parts) + f"\n\n{footer}"

    logger.info(
        "Assembled context: %d chunks, ~%d tokens (budget: %d)",
        len(included),
        used_tokens,
        budget,
    )

    return context, included
