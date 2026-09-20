"""Module-level async clients + retrieval adapter for routes_v4.

v4 handlers take an AsyncOpenAI client and a retrieval_fn as kwargs
so every handler is pure. Those dependencies live here as lazy
singletons so the process has one client + one adapter rather than
per-module copies. Tests can ``reset_clients()`` between cases.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer, get_canonicalizer
from config import settings
from retrieval.ml_library import MLLibrary, get_library
from retrieval.search import hybrid_search

logger = logging.getLogger(__name__)


_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    """Lazy singleton. Honors active LLM provider (OpenRouter / OpenAI)."""
    global _client
    if _client is None:
        base_url = settings.effective_base_url
        kwargs: dict[str, Any] = {
            "api_key": settings.effective_api_key,
            "timeout": 60.0,
        }
        if base_url:
            kwargs["base_url"] = base_url
            if "openrouter" in base_url.lower():
                kwargs["default_headers"] = {
                    "HTTP-Referer": "https://brady-copilot.local",
                    "X-Title": "Brady AI Writing Co-Pilot",
                }
        _client = AsyncOpenAI(**kwargs)
    return _client


def reset_clients() -> None:
    """Reset module-level singletons. Tests only."""
    global _client
    _client = None


def get_canon() -> Canonicalizer:
    """Passthrough — exposed here so routes_v4 has a single import
    surface for ``dependencies`` and the test seams live in one place."""
    return get_canonicalizer()


def get_ml_library() -> MLLibrary:
    """Passthrough to retrieval.ml_library.get_library() — library is
    loaded once at process start (see lifespan)."""
    return get_library()


# ----------------------------------------------------------------------
# Retrieval adapter
# ----------------------------------------------------------------------
#
# Handlers call a retrieval_fn(**kwargs) that returns RetrievedChunks.
# The kwargs come from handlers._retrieval.run_retrieval — they include
# query, intent, query_type, plus optional grade_level/writing_mode/
# writing_trait/strategy_name. The adapter calls hybrid_search with the
# handler kwargs and returns its output verbatim — hybrid_search already
# reranks internally (so Brady's source-priority rule fires — Launch
# content in top-3 for persuasive and K-12 queries) and trims to the
# intent-based final_k. Reranking again here would double-apply the
# priority boost (base*boost**2) — see tests/unit/test_retrieval_fn.py.
#
# We don't do library-precheck here — the SCRIPTED_ML handler runs its
# own precheck (see handlers/scripted_ml.py). Keeping those two concerns
# separate makes the adapter usable by every handler equally.


async def retrieval_fn(
    *,
    query: str,
    intent: str | None = None,
    query_type: str | None = None,
    grade_level: str | None = None,
    writing_mode: str | None = None,
    writing_trait: str | None = None,
    strategy_name: str | None = None,
    smekens_terms: list[str] | None = None,
    top_k: int | None = None,
) -> list[Any]:
    """Route handler kwargs through hybrid_search.

    Returns hybrid_search's output verbatim — already reranked
    (tier-boosted) and trimmed to the final top-k. Handler code passes
    the chunks to the assembler to build the LLM-visible context string.
    """
    candidates = await hybrid_search(
        query=query,
        intent=intent,
        grade_level=grade_level,
        writing_mode=writing_mode,
        writing_trait=writing_trait,
        strategy_name=strategy_name,
        smekens_terms=smekens_terms,
        top_k=top_k,
        query_type=query_type,
    )
    if not candidates:
        return []

    # hybrid_search already reranked (with triggers, over the full candidate
    # pool) and trimmed to the intent-based final_k. A second rerank here only
    # squared the boost (base*boost**2) and dropped the trigger context.
    logger.debug(
        "retrieval_fn: query_type=%s intent=%s grade=%s mode=%s → %d chunks",
        query_type, intent, grade_level, writing_mode, len(candidates),
    )
    return candidates
