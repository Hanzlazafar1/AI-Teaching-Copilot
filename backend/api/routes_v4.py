"""v4 chat endpoint: QU → dispatcher → conversation append.

The v3 rules layer (session_ledger.py, session.py state machine,
predicate cascade) is gone. The v4 flow is:

  1. Load Conversation + SessionHandshakes from the store.
  2. Run QU against the full conversation → TurnIntent.
  3. Append the user Turn with its intent.
  4. Dispatch to the request_type's handler → TurnOutcome.
  5. Append the assistant Turn with grounding + structured + quality.
  6. Save the conversation.
  7. Build a ChatResponse the frontend already renders.

Health endpoints, error envelopes, request-id middleware, logging
middleware all live in main.py and stay unchanged.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter

from api.conversation_store import get_store
from api.dependencies import (
    get_canon,
    get_ml_library,
    get_openai_client,
    retrieval_fn,
)
from api.errors import AppError
from api.models import (
    ChatRequest,
    ChatResponse,
    ParsedQueryInfo,
    SourceInfo,
    resolve_models,
)
from config import settings
from handlers import dispatch
from query.qu_v4 import understand
from schemas import (
    Conversation,
    Quality,
    Role,
    SessionHandshakes,
    Turn,
    TurnIntent,
    TurnOutcome,
)

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------------
# Per-user rate limiter (pilot — in-memory, resets on restart)
# ----------------------------------------------------------------------


_rate_limits: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(user_id: str) -> bool:
    """Return True if the user is over the per-hour cap."""
    now = time.time()
    window = 3600.0
    ts = _rate_limits[user_id] = [t for t in _rate_limits[user_id] if now - t < window]
    if len(ts) >= settings.rate_limit_per_hour:
        return True
    ts.append(now)
    return False


# ----------------------------------------------------------------------
# /api/chat
# ----------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Main chat endpoint — QU-driven, conversation-as-memory."""
    user_id = request.user_id or "anonymous"
    session_id = request.session_id or str(uuid.uuid4())

    if _check_rate_limit(user_id):
        raise AppError.rate_limited(retry_after=3600)

    models = resolve_models(request.model, settings)

    client = get_openai_client()
    canon = get_canon()
    library = get_ml_library()
    store = get_store()

    conversation, handshakes = store.load(session_id, user_id=user_id)

    # --- QU + dispatch under a hard deadline (finding F28) -------------
    # The full QU -> dispatch sequence (query understanding + up to
    # ``max_generation_attempts`` generation attempts + judge calls + an
    # optional repair pass) must finish within ``route_timeout_seconds``.
    # Without a deadline a pathological run (e.g. every attempt clipping the
    # upstream 60s call timeout) could pin a worker far past the intended
    # budget. Exceeding the deadline raises ``asyncio.TimeoutError``, which
    # main.py's ``_asyncio_timeout_handler`` maps to a 504 (retry-worthy).
    async def _understand_and_dispatch() -> tuple[TurnIntent, TurnOutcome]:
        # --- Query Understanding ---------------------------------------
        intent = await understand(
            conversation=conversation,
            new_user_message=request.message,
            client=client,
            model=models.query,
            handshakes=handshakes,
            canonicalizer=canon,
        )

        # --- Append user turn now that its intent is known -------------
        user_turn = Turn(
            index=len(conversation.turns),
            role=Role.USER,
            text=request.message,
            intent=intent,
        )
        conversation.append(user_turn)

        # --- Dispatch to handler ---------------------------------------
        outcome = await dispatch(
            intent=intent,
            conversation=_conversation_without_last_user(conversation),
            handshakes=handshakes,
            new_user_message=request.message,
            client=client,
            models=models,
            canonicalizer=canon,
            retrieval_fn=retrieval_fn,
            library=library,
        )
        return intent, outcome

    intent, outcome = await asyncio.wait_for(
        _understand_and_dispatch(),
        timeout=settings.route_timeout_seconds,
    )

    # --- Append assistant turn + save ----------------------------------
    assistant_turn = Turn(
        index=len(conversation.turns),
        role=Role.ASSISTANT,
        text=outcome.response_text,
        structured=outcome.structured,
        offered_skills=list(outcome.offered_skills),
        clarifying_for=outcome.clarifying_for,
        grounding=list(outcome.grounding),
        quality=outcome.quality,
    )
    conversation.append(assistant_turn)
    store.save(session_id, conversation, handshakes)

    return _build_response(
        outcome=outcome,
        intent=intent,
        conversation=conversation,
        handshakes=handshakes,
        session_id=session_id,
    )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _conversation_without_last_user(conversation: Conversation) -> Conversation:
    """Handlers render the conversation as LLM context. The user message
    we're about to respond to is passed separately via ``new_user_message``
    so the handler's prompt builders don't double-count it. Return a
    shallow Conversation view with the last turn trimmed IF it's the
    user turn we just appended.

    We construct a new Conversation to avoid mutating the store's copy;
    the Turn objects themselves are shared (immutable except .quality
    flip via validate_assignment, which we don't do here).
    """
    if not conversation.turns:
        return conversation
    last = conversation.turns[-1]
    if last.role is not Role.USER:
        return conversation
    view = Conversation(
        session_id=conversation.session_id,
        user_id=conversation.user_id,
        turns=list(conversation.turns[:-1]),
    )
    return view


def _build_response(
    *,
    outcome: TurnOutcome,
    intent: TurnIntent,
    conversation: Conversation,
    handshakes: SessionHandshakes,
    session_id: str,
) -> ChatResponse:
    """Map (outcome, intent) onto the legacy-compatible ChatResponse
    shape so the Streamlit frontend keeps rendering."""
    response_body: Any
    response_intent: str
    if outcome.structured is not None:
        response_body = outcome.structured
        response_intent = "mini_lesson"
    else:
        response_body = outcome.response_text
        response_intent = intent.request_type.value.lower()

    sources = [_ground_to_source(g) for g in outcome.grounding]
    quality = _map_quality(outcome.quality)

    return ChatResponse(
        response=response_body,
        intent=response_intent,
        quality=quality,
        quality_warning=_warning_for(outcome),
        sources=sources,
        retrieved_context=outcome.retrieved_context,
        judge_score=_judge_score(outcome),
        ungrounded_terms=[],
        parsed_query=_intent_to_parsed(intent),
        session_state=_session_state_view(conversation, handshakes, intent),
    )


def _ground_to_source(ref) -> SourceInfo:
    return SourceInfo(
        chunk_id=ref.chunk_id,
        source_document=ref.source_document,
        content_type="",  # not carried on ChunkRef — frontend tolerates empty
        relevance_score=0.0,
        source_tier=getattr(ref, "source_tier", None),
    )


def _map_quality(q: Quality) -> str:
    if q is Quality.VALID:
        return "validated"
    if q is Quality.LOW:
        return "low_quality"
    return "error"


def _warning_for(outcome: TurnOutcome) -> str | None:
    if outcome.quality is Quality.LOW and outcome.validation_errors:
        return "; ".join(outcome.validation_errors[:3])
    return None


def _judge_score(outcome: TurnOutcome) -> float | None:
    """Average the judge's dimension scores (1-10 scale).

    `bool` is a subclass of `int` in Python, so the pass-through flag
    ``passes`` would otherwise fold into the average as 0 or 1 and drag
    a real 8/10 down to 6.25/10. Exclude booleans explicitly.
    """
    scores = getattr(outcome, "judge_scores", None)
    if not scores:
        return None
    values = [
        s for s in scores.values()
        if isinstance(s, (int, float)) and not isinstance(s, bool)
    ]
    return float(sum(values) / len(values)) if values else None


def _intent_to_parsed(intent: TurnIntent) -> ParsedQueryInfo:
    """Project v4 TurnIntent into the v3-style ParsedQueryInfo so the
    frontend's query debug panel keeps rendering."""
    return ParsedQueryInfo(
        intent=intent.request_type.value.lower(),
        grade_level=intent.grade.value if intent.grade else None,
        writing_trait=intent.trait.value if intent.trait else None,
        writing_mode=intent.mode.value if intent.mode else None,
        strategy_name=intent.skill.as_stated if intent.skill else None,
        smekens_terms=list(intent.required_triggers),
        follow_up_type="refers_to_prior" if intent.refers_to_prior else "none",
        query_type=intent.request_type.value,
        query_specificity="broad",
        topic_shift_confidence=0.0,
        is_correction=intent.request_type.value == "CORRECTION",
    )


def _session_state_view(
    conversation: Conversation,
    handshakes: SessionHandshakes,
    intent: TurnIntent,
) -> dict[str, Any]:
    """Flat view for the Streamlit `Session Memory` sidebar.

    v3 surfaced ~20 fields from the SessionLedger. v4 has no ledger —
    everything lives on the conversation. We project the most recent
    intent's pedagogical fields plus pending-handshake signals so the
    sidebar has something useful to render.
    """
    latest = _latest_user_intent(conversation) or intent
    return {
        "grade": latest.grade.value if latest.grade else None,
        "mode": latest.mode.value if latest.mode else None,
        "trait": latest.trait.value if latest.trait else None,
        "skill": latest.skill.as_stated if latest.skill else None,
        "skill_canonical": latest.skill.canonical if latest.skill else None,
        "last_response_type": _last_assistant_type(conversation),
        "last_request_type": latest.request_type.value,
        "required_triggers": list(latest.required_triggers),
        "refers_to_prior": latest.refers_to_prior,
        "needs_confirmation": latest.needs_confirmation,
        "missing_required": list(latest.missing_required),
        "pending_ml_confirmation": (
            handshakes.ml_confirmation.model_dump()
            if handshakes.ml_confirmation else None
        ),
        "pending_library_offer": (
            handshakes.library_offer.model_dump()
            if handshakes.library_offer else None
        ),
        "clarification_pending": (
            handshakes.clarification.model_dump()
            if handshakes.clarification else None
        ),
        "turn_count": len(conversation.turns),
    }


def _latest_user_intent(conversation: Conversation) -> TurnIntent | None:
    for t in reversed(conversation.turns):
        if t.role is Role.USER and t.intent is not None:
            return t.intent
    return None


def _last_assistant_type(conversation: Conversation) -> str | None:
    for t in reversed(conversation.turns):
        if t.role is Role.ASSISTANT:
            if isinstance(t.structured, dict) and "skill_focus" in t.structured:
                return "SCRIPTED_ML"
            # Walk back one more for the triggering user intent — the
            # assistant turn's "type" mirrors the user's request_type.
            idx = t.index
            for j in range(idx - 1, -1, -1):
                prev = conversation.turns[j]
                if prev.role is Role.USER and prev.intent is not None:
                    return prev.intent.request_type.value
            return None
    return None
