"""Tests for api.routes_v4 — the v4 chat endpoint.

LLM + retrieval are mocked. We verify:
  - QU is called with the current conversation (NOT including the new
    user message).
  - Dispatcher is called with the right intent and conversation view.
  - Response + conversation persist across turns.
  - Rate limit trips with 429.
  - Model profile override threads into the generation model kwarg.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import conversation_store as store_mod
from api import dependencies as deps_mod
from api import routes_v4
from schemas import (
    ChunkRef,
    Quality,
    RequestType,
    Role,
    SessionHandshakes,
    SkillSpec,
    TurnIntent,
    TurnOutcome,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Each test starts with fresh store + dependency singletons."""
    store_mod.reset_store()
    deps_mod.reset_clients()
    routes_v4._rate_limits.clear()
    yield
    store_mod.reset_store()
    deps_mod.reset_clients()
    routes_v4._rate_limits.clear()


@pytest.fixture
def app(monkeypatch):
    """Build a FastAPI app with mocked deps + the AppError handler.

    main.py registers global exception handlers on the FastAPI app.
    Tests here build a slimmer app (just the v4 router), so we
    re-register the AppError handler so raised AppErrors turn into
    their structured HTTP envelope instead of 500-ing."""
    # Stub openai client factory — no real network
    monkeypatch.setattr(deps_mod, "get_openai_client", lambda: object())
    # Stub library + canonicalizer so routes_v4 doesn't hit disk
    monkeypatch.setattr(deps_mod, "get_ml_library", lambda: None)
    monkeypatch.setattr(deps_mod, "get_canon", lambda: object())

    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from api.errors import AppError

    app = FastAPI()
    app.include_router(routes_v4.router)

    @app.exception_handler(AppError)
    async def _handle(_req: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_response().model_dump(mode="json"),
            headers=exc.headers or None,
        )

    return app


# ----------------------------------------------------------------------
# Mock seams
# ----------------------------------------------------------------------


def _stub_qu(monkeypatch, intent: TurnIntent) -> list[dict[str, Any]]:
    """Replace query.qu_v4.understand with a recorder. Captures
    ``len(conversation.turns)`` at call time (the conversation object
    is mutated in place by routes_v4, so holding a reference would see
    a later state)."""
    calls: list[dict[str, Any]] = []

    async def _fake(**kwargs):
        snap = dict(kwargs)
        conv = kwargs.get("conversation")
        snap["_turns_at_call"] = len(conv.turns) if conv else 0
        calls.append(snap)
        return intent

    monkeypatch.setattr(routes_v4, "understand", _fake)
    return calls


def _stub_dispatch(monkeypatch, outcome: TurnOutcome) -> list[dict[str, Any]]:
    """Replace handlers.dispatch with a recorder. Captures turn count
    at call time (same reason as _stub_qu)."""
    calls: list[dict[str, Any]] = []

    async def _fake(**kwargs):
        snap = dict(kwargs)
        conv = kwargs.get("conversation")
        snap["_turns_at_call"] = len(conv.turns) if conv else 0
        calls.append(snap)
        return outcome

    monkeypatch.setattr(routes_v4, "dispatch", _fake)
    return calls


def _valid_outcome(text: str = "hello teacher") -> TurnOutcome:
    return TurnOutcome(
        response_text=text,
        structured=None,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
    )


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------


def test_chat_runs_qu_then_dispatch_and_persists_conversation(
    app, monkeypatch
) -> None:
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
    )
    qu_calls = _stub_qu(monkeypatch, intent)
    disp_calls = _stub_dispatch(monkeypatch, _valid_outcome("coaching reply"))

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "what are topic sentences?", "session_id": "s1"
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["response"] == "coaching reply"
    assert body["intent"] == "coaching"
    assert body["quality"] == "validated"

    # QU saw the empty conversation (first turn) — before the user
    # turn gets appended by the chat handler.
    assert len(qu_calls) == 1
    assert qu_calls[0]["new_user_message"] == "what are topic sentences?"
    assert qu_calls[0]["_turns_at_call"] == 0

    # Dispatch saw the intent + a conversation view WITHOUT the new
    # user turn (the handler's prompt adds new_user_message itself).
    assert len(disp_calls) == 1
    assert disp_calls[0]["intent"].request_type is RequestType.COACHING
    assert disp_calls[0]["_turns_at_call"] == 0

    # Second turn: conversation should now have 2 persisted turns
    qu_calls.clear()
    disp_calls.clear()
    _stub_qu(monkeypatch, intent)  # re-stub since monkeypatch replaced
    _stub_dispatch(monkeypatch, _valid_outcome("second reply"))
    client.post("/api/chat", json={
        "message": "more details?", "session_id": "s1"
    })

    stored = store_mod.get_store().load("s1")[0]
    # Persisted turns: user1, asst1, user2, asst2
    assert [t.role for t in stored.turns] == [
        Role.USER, Role.ASSISTANT, Role.USER, Role.ASSISTANT
    ]
    assert stored.turns[0].text == "what are topic sentences?"
    assert stored.turns[1].text == "coaching reply"
    assert stored.turns[2].text == "more details?"
    assert stored.turns[3].text == "second reply"

    # Turn 0 (user) carries the intent; Turn 1 (assistant) carries quality
    assert stored.turns[0].intent is not None
    assert stored.turns[1].quality is Quality.VALID


def test_chat_returns_structured_body_for_scripted_ml(app, monkeypatch) -> None:
    intent = TurnIntent(request_type=RequestType.SCRIPTED_ML)
    _stub_qu(monkeypatch, intent)
    structured = {
        "skill_focus": "topic sentences",
        "step_1_introduce": "...",
        "step_2a_tell": "...",
        "step_2b_show": "...",
        "step_3_interact": "...",
        "step_4_close": "...",
    }
    _stub_dispatch(monkeypatch, TurnOutcome(
        response_text="rendered lesson text",
        structured=structured,
        grounding=[ChunkRef(chunk_id="c1", source_document="lww312",
                             page_number=64)],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
    ))

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "give me a lesson", "session_id": "s2"
    })
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == structured
    assert body["intent"] == "mini_lesson"
    assert body["sources"][0]["chunk_id"] == "c1"


# ----------------------------------------------------------------------
# Quality mapping
# ----------------------------------------------------------------------


def test_chat_maps_low_quality_with_warning(app, monkeypatch) -> None:
    _stub_qu(monkeypatch, TurnIntent(request_type=RequestType.COACHING))
    _stub_dispatch(monkeypatch, TurnOutcome(
        response_text="partial",
        structured=None,
        grounding=[],
        quality=Quality.LOW,
        retry_count=2,
        validation_errors=["missing closing phrase", "forbidden word 'discuss'"],
    ))

    client = TestClient(app)
    r = client.post("/api/chat", json={"message": "q", "session_id": "sLow"})
    assert r.status_code == 200
    body = r.json()
    assert body["quality"] == "low_quality"
    assert body["quality_warning"]
    assert "missing closing phrase" in body["quality_warning"]


# ----------------------------------------------------------------------
# Rate limit
# ----------------------------------------------------------------------


def test_chat_rate_limit_returns_429(app, monkeypatch) -> None:
    _stub_qu(monkeypatch, TurnIntent(request_type=RequestType.COACHING))
    _stub_dispatch(monkeypatch, _valid_outcome())
    # Fill the per-user window
    from config import settings
    import time
    user = "ratelimited_user"
    routes_v4._rate_limits[user] = [time.time()] * settings.rate_limit_per_hour

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "hi", "user_id": user, "session_id": "s"
    })
    assert r.status_code == 429


# ----------------------------------------------------------------------
# Model profile
# ----------------------------------------------------------------------


def test_chat_profile_threads_split_models(app, monkeypatch) -> None:
    """gpt-4o profile -> QU on the QUERY model (gpt-4o-mini); dispatch gets
    the full ModelSet with generation=gpt-4o. Locks the F27 split so QU
    can't silently regress to the generation model (was asserted == 'gpt-4o')."""
    intent = TurnIntent(request_type=RequestType.COACHING)
    qu_calls = _stub_qu(monkeypatch, intent)
    disp_calls = _stub_dispatch(monkeypatch, _valid_outcome())

    client = TestClient(app)
    r = client.post("/api/chat", json={"message": "hi", "session_id": "s", "model": "gpt-4o"})
    assert r.status_code == 200
    assert qu_calls[0]["model"] == "gpt-4o-mini"            # QU on the query model
    assert disp_calls[0]["models"].generation == "gpt-4o"  # generation on gen model
    assert disp_calls[0]["models"].query == "gpt-4o-mini"
    assert disp_calls[0]["models"].judge == "gpt-4o-mini"


def test_chat_unknown_model_falls_back_to_default_query(app, monkeypatch) -> None:
    intent = TurnIntent(request_type=RequestType.COACHING)
    qu_calls = _stub_qu(monkeypatch, intent)
    _stub_dispatch(monkeypatch, _valid_outcome())
    from config import settings

    client = TestClient(app)
    r = client.post("/api/chat", json={"message": "hi", "session_id": "s", "model": "does-not-exist"})
    assert r.status_code == 200
    assert qu_calls[0]["model"] == settings.openai_query_model  # NOT generation


# ----------------------------------------------------------------------
# Session state projection
# ----------------------------------------------------------------------


def test_chat_response_session_state_has_grade_skill_and_counts(
    app, monkeypatch
) -> None:
    from schemas import GradeSpec, ModeSpec, TraitSpec

    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        grade=GradeSpec(value="3", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        trait=TraitSpec(value="Ideas", stated_explicit=False, confidence=0.8),
        skill=SkillSpec(canonical="topic sentences",
                         as_stated="topic sentence and supporting details"),
        required_triggers=["pizza-table"],
    )
    _stub_qu(monkeypatch, intent)
    _stub_dispatch(monkeypatch, _valid_outcome())

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "how do I teach topic sentences?", "session_id": "sS"
    })
    body = r.json()
    state = body["session_state"]
    assert state["grade"] == "3"
    assert state["mode"] == "Inform"
    assert state["trait"] == "Ideas"
    assert state["skill"] == "topic sentence and supporting details"
    assert state["skill_canonical"] == "topic sentences"
    assert state["required_triggers"] == ["pizza-table"]
    assert state["turn_count"] == 2  # user + assistant just added
    assert state["last_request_type"] == "HOW_TO_TEACH"


def test_chat_response_session_state_has_nested_handshake_dicts(
    app, monkeypatch
) -> None:
    _stub_qu(monkeypatch, TurnIntent(request_type=RequestType.COACHING))
    _stub_dispatch(monkeypatch, _valid_outcome())

    # Pre-seed a pending library offer on this session
    from schemas.handshakes import PendingLibraryOffer
    store = store_mod.get_store()
    _, hs = store.load("s_handshake")
    hs.library_offer = PendingLibraryOffer(
        ml_id="k2-s2-ml6", skill="x", grade="K", offered_at_turn=0,
    )

    client = TestClient(app)
    r = client.post("/api/chat", json={"message": "hi", "session_id": "s_handshake"})
    state = r.json()["session_state"]
    assert state["pending_library_offer"] is not None
    assert state["pending_library_offer"]["ml_id"] == "k2-s2-ml6"


# ----------------------------------------------------------------------
# Parsed-query projection
# ----------------------------------------------------------------------


def test_chat_response_parsed_query_reflects_intent(app, monkeypatch) -> None:
    from schemas import GradeSpec

    intent = TurnIntent(
        request_type=RequestType.CORRECTION,
        grade=GradeSpec(value="4", stated_explicit=True),
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
        refers_to_prior=True,
    )
    _stub_qu(monkeypatch, intent)
    _stub_dispatch(monkeypatch, _valid_outcome())

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "actually 4th grade", "session_id": "sCorr"
    })
    pq = r.json()["parsed_query"]
    assert pq["intent"] == "correction"
    assert pq["grade_level"] == "4"
    assert pq["follow_up_type"] == "refers_to_prior"
    assert pq["is_correction"] is True
    assert pq["query_type"] == "CORRECTION"


# ----------------------------------------------------------------------
# Route deadline (F28) — route_timeout_seconds enforced via asyncio.wait_for
#
# The QU + dispatch body (query-understanding + up to 3 generation
# attempts + 3 judge calls + an optional repair pass) runs under a hard
# deadline. Exceeding it raises asyncio.TimeoutError, which main.py's
# _asyncio_timeout_handler maps to a 504 so a wedged request can't tie up
# a worker indefinitely. route_timeout_seconds was a dead knob before F28.
# ----------------------------------------------------------------------


def _stub_slow_dispatch(monkeypatch, *, sleep_s: float) -> None:
    """Replace handlers.dispatch with a coroutine that sleeps past a tiny
    injected route deadline. The sleep is a CEILING, not a real wait: once
    the deadline trips, asyncio.wait_for cancels this coroutine mid-sleep,
    so the test resolves in ~route_timeout_seconds (~0.02s), never sleep_s."""
    import asyncio as _asyncio

    async def _fake(**kwargs):
        await _asyncio.sleep(sleep_s)
        return _valid_outcome("should never be returned")

    monkeypatch.setattr(routes_v4, "dispatch", _fake)


def _register_timeout_handler(app) -> None:
    """Register the REAL main.py handler so the test exercises the actual
    production asyncio.TimeoutError -> 504 envelope wiring, not a duplicate."""
    import asyncio as _asyncio

    from main import _asyncio_timeout_handler

    app.add_exception_handler(_asyncio.TimeoutError, _asyncio_timeout_handler)


def test_chat_fast_path_still_succeeds_under_deadline(app, monkeypatch) -> None:
    """The wait_for wrapping must not affect a normal (fast) request — a
    request that finishes well within the deadline still returns 200."""
    from config import settings

    monkeypatch.setattr(settings, "route_timeout_seconds", 5.0)  # generous
    _stub_qu(monkeypatch, TurnIntent(request_type=RequestType.COACHING))
    _stub_dispatch(monkeypatch, _valid_outcome("fast reply"))

    client = TestClient(app)
    r = client.post("/api/chat", json={"message": "hi", "session_id": "fast"})
    assert r.status_code == 200, r.text
    assert r.json()["response"] == "fast reply"


def test_chat_slow_path_trips_deadline_returns_504(app, monkeypatch) -> None:
    """A run exceeding route_timeout_seconds -> asyncio.TimeoutError ->
    main.py's handler -> 504 timed_out envelope (finding F28)."""
    from config import settings

    _register_timeout_handler(app)
    monkeypatch.setattr(settings, "route_timeout_seconds", 0.02)  # tiny
    _stub_qu(monkeypatch, TurnIntent(request_type=RequestType.SCRIPTED_ML))
    _stub_slow_dispatch(monkeypatch, sleep_s=0.5)  # 0.5s >> 0.02s -> deadline wins

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "give me a lesson", "session_id": "slow"
    })
    assert r.status_code == 504, r.text
    assert r.json()["error_code"] == "timed_out"


def test_chat_deadline_raises_asyncio_timeout_at_route(app, monkeypatch) -> None:
    """Independent of the 504 handler: the route itself enforces the deadline,
    so a too-slow dispatch propagates asyncio.TimeoutError out of the endpoint
    (no timeout handler registered here -> TestClient re-raises the original)."""
    import asyncio

    from config import settings

    monkeypatch.setattr(settings, "route_timeout_seconds", 0.02)
    _stub_qu(monkeypatch, TurnIntent(request_type=RequestType.COACHING))
    _stub_slow_dispatch(monkeypatch, sleep_s=0.5)

    client = TestClient(app)  # default raise_server_exceptions=True
    with pytest.raises(asyncio.TimeoutError):
        client.post("/api/chat", json={"message": "hi", "session_id": "raise"})


# ----------------------------------------------------------------------
# offered_skills persistence — the pick-list must survive the API boundary
# ----------------------------------------------------------------------


def test_chat_persists_offered_skills_onto_the_assistant_turn(
    app, monkeypatch
) -> None:
    """The offering turn's pick-list must reach the STORE, because the next
    turn's "number 4" resolves against it.

    This is the boundary that has silently dropped fields before (the S3
    guard; Fm3's title-case): the handler computes something correct and the
    Turn constructor just doesn't copy it. A field-by-field constructor
    cannot be trusted without a test that reads the stored turn back.
    """
    intent = TurnIntent(request_type=RequestType.PLAN_UNIT)
    _stub_qu(monkeypatch, intent)
    offered = [
        "Recognize opinionated/debatable topics",
        "Determine the strongest side",
        "State an opinion to a particular audience",
        "Generate reasons to support an opinion about the topic",
    ]
    outcome = TurnOutcome(
        response_text="1. Recognize...\n\n2. Determine...",
        structured=None,
        offered_skills=offered,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
    )
    _stub_dispatch(monkeypatch, outcome)

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "Plan a persuasive writing unit for 4th grade",
        "session_id": "offered-1",
    })
    assert r.status_code == 200, r.text

    convo, _ = store_mod.get_store().load("offered-1")
    assistant_turns = [t for t in convo.turns if t.role is Role.ASSISTANT]
    assert len(assistant_turns) == 1
    assert assistant_turns[0].offered_skills == offered


def test_chat_leaves_offered_skills_empty_for_a_non_offering_turn(
    app, monkeypatch
) -> None:
    """A turn that offered no list must persist no list — otherwise a later
    ordinal would resolve against a pick-list that was never shown."""
    intent = TurnIntent(request_type=RequestType.COACHING)
    _stub_qu(monkeypatch, intent)
    _stub_dispatch(monkeypatch, _valid_outcome("just prose"))

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "what are topic sentences?", "session_id": "offered-2"
    })
    assert r.status_code == 200, r.text

    convo, _ = store_mod.get_store().load("offered-2")
    assistant_turns = [t for t in convo.turns if t.role is Role.ASSISTANT]
    assert assistant_turns[0].offered_skills == []


# ----------------------------------------------------------------------
# The pending clarify must survive the API boundary
# ----------------------------------------------------------------------
#
# Same failure class as offered_skills (and Fm3, and S3): a rule that is
# correct inside the handler but never reaches the next turn. QU restores the
# pending request_type by reading Turn.clarifying_for, so if this constructor
# drops the field the whole resume is inert — and every unit test above it
# still passes.


def test_chat_persists_the_pending_clarify_type_onto_the_turn(
    app, monkeypatch
) -> None:
    intent = TurnIntent(request_type=RequestType.SCRIPTED_ML)
    _stub_qu(monkeypatch, intent)
    _stub_dispatch(monkeypatch, TurnOutcome(
        response_text="What grade level do you teach? "
                      "What writing skill are you working on?",
        structured=None,
        clarifying_for=RequestType.SCRIPTED_ML,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
    ))

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "Can you give me a scripted mini-lesson?",
        "session_id": "clarify-1",
    })
    assert r.status_code == 200, r.text

    convo, _ = store_mod.get_store().load("clarify-1")
    assistant_turns = [t for t in convo.turns if t.role is Role.ASSISTANT]
    assert len(assistant_turns) == 1
    assert assistant_turns[0].clarifying_for is RequestType.SCRIPTED_ML


def test_chat_leaves_the_pending_clarify_type_unset_for_a_normal_turn(
    app, monkeypatch
) -> None:
    """No question was asked, so nothing is pending — a later bare message must
    not be pinned to a request the app never clarified."""
    _stub_qu(monkeypatch, TurnIntent(request_type=RequestType.COACHING))
    _stub_dispatch(monkeypatch, _valid_outcome("just prose"))

    client = TestClient(app)
    r = client.post("/api/chat", json={
        "message": "what are topic sentences?", "session_id": "clarify-2"
    })
    assert r.status_code == 200, r.text

    convo, _ = store_mod.get_store().load("clarify-2")
    assistant_turns = [t for t in convo.turns if t.role is Role.ASSISTANT]
    assert assistant_turns[0].clarifying_for is None
