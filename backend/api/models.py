"""Pydantic request/response schemas for the API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel, Field

from api.request_context import get_request_id

logger = logging.getLogger(__name__)


def _current_req_id() -> Optional[str]:
    """Default factory for ``ChatResponse.request_id`` — reads the per-request
    ContextVar so every response constructed inside an HTTP request is
    auto-stamped. Returns ``None`` (not empty string) outside a request
    so the field is omitted cleanly.
    """
    rid = get_request_id()
    return rid or None


# Model profiles the frontend can switch between. Each profile pairs a
# generation model (used by lesson / coaching / how-to-teach / plan-unit /
# repair) with its matching query-understanding model (used by QU/intent
# extraction) and judge model (lighter sibling used for scoring).
# Pairing them at the profile level means Brady's "GPT-5.4" choice
# transparently routes generation to gpt-5.4, query-understanding to
# gpt-5.4-mini, AND judging to gpt-5.4-mini, without the frontend having
# to pick three values. Extend this map when we want to expose a new
# profile in the testing UI — the whitelist elsewhere (route handler)
# keeps arbitrary client-supplied strings from reaching OpenAI.
MODEL_PROFILES: dict[str, dict[str, str]] = {
    "gpt-4o":  {"generation": "gpt-4o",  "query": "gpt-4o-mini",  "judge": "gpt-4o-mini"},
    "gpt-5.4": {"generation": "gpt-5.4", "query": "gpt-5.4-mini", "judge": "gpt-5.4-mini"},
}


@dataclass(frozen=True)
class ModelSet:
    """The three model IDs a single chat turn uses. Resolved once per
    request (from the profile the client sent, or the configured defaults)
    and threaded through routes -> dispatch. Keeps generation on the
    flagship while query-understanding + the judge use the cheap sibling."""
    generation: str
    query: str
    judge: str


def resolve_models(requested: str | None, settings) -> ModelSet:
    """Translate a frontend profile name into the turn's three model IDs.
    Known profile -> its (generation, query, judge). None/unknown -> the
    configured defaults. Honors active provider prefixing."""
    defaults = ModelSet(
        generation=settings.effective_generation_model,
        query=settings.effective_query_model,
        judge=settings.effective_judge_model,
    )
    if not requested:
        return defaults
    profile = MODEL_PROFILES.get(requested)
    if not profile:
        logger.warning("Unknown model profile %r — falling back to defaults", requested)
        return defaults

    gen = profile.get("generation", defaults.generation)
    q = profile.get("query", defaults.query)
    j = profile.get("judge", defaults.judge)

    is_openrouter = getattr(settings, "llm_provider", "openrouter").lower() == "openrouter"
    if is_openrouter:
        if "/" not in gen:
            gen = f"openai/{gen}"
        if "/" not in q:
            q = f"openai/{q}"
        if "/" not in j:
            j = f"openai/{j}"
    else:
        gen = gen.replace("openai/", "")
        q = q.replace("openai/", "")
        j = j.replace("openai/", "")

    return ModelSet(generation=gen, query=q, judge=j)


class ChatRequest(BaseModel):
    """POST /api/chat request body."""
    message: str = Field(max_length=100000)
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    # Optional model-profile override. When set and present in MODEL_PROFILES,
    # generation (lesson / coaching / how-to-teach / plan-unit / repair)
    # routes to the profile's generation model, query-understanding routes
    # to its paired query model, AND the judge routes to its paired judge
    # model. Invalid values are silently ignored — we fall back to the
    # configured defaults rather than failing a request because the UI
    # sent an unknown profile name.
    model: Optional[str] = None


class SourceInfo(BaseModel):
    """A single retrieved source chunk."""
    chunk_id: str
    source_document: str
    content_type: str
    relevance_score: float
    source_tier: Optional[int] = None


class ParsedQueryInfo(BaseModel):
    """The extracted query fields, returned for transparency."""
    intent: str
    grade_level: Optional[str] = None
    writing_trait: Optional[str] = None
    writing_mode: Optional[str] = None
    strategy_name: Optional[str] = None
    smekens_terms: list[str] = []
    follow_up_type: str = "none"
    # Phase 5 extensions — surfaced so acceptance tests can assert dispatch.
    query_type: str = "DEFAULT"
    query_specificity: str = "broad"
    topic_shift_confidence: float = 0.0
    is_correction: bool = False


class ChatResponse(BaseModel):
    """POST /api/chat response body."""
    response: Any = Field(description="MiniLesson dict or free-text string")
    intent: str
    quality: str = Field(
        description="validated | acceptable | low_quality | unscored | error"
    )
    quality_warning: Optional[str] = None
    sources: list[SourceInfo] = []
    retrieved_context: str = ""
    judge_score: Optional[float] = None
    ungrounded_terms: list[str] = []
    follow_up_question: Optional[str] = None
    parsed_query: Optional[ParsedQueryInfo] = None
    # Flat view of the session's accumulated state (grade, mode, trait, skill,
    # last_response_type, last_*, pending_*). Populated by the chat handler
    # from ``SessionLedger.to_flat_dict()``. Exposed so the Streamlit tester
    # frontend can render a "Session Memory" sidebar — Brady's key diagnostic
    # for "does the system remember what I told it across turns?".
    session_state: Optional[dict] = None
    # Correlation id for this response — auto-populated from the per-request
    # ContextVar (Phase 11.1). Lets a client include `req_id` in a bug report
    # so engineers can grep logs directly. Falls back to None outside a
    # request context (e.g. unit tests constructing a ChatResponse manually).
    request_id: Optional[str] = Field(default_factory=_current_req_id)
