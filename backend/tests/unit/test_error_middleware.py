"""Integration test for Phase 11.1 — FastAPI middleware + exception handlers.

Uses ``TestClient`` on a minimal side-app (not the real copilot ``main.app``) so
the test doesn't require Qdrant, the ML library, or OpenAI. We install only
the request-id middleware + exception handlers + a few test routes that raise
the errors we expect real handlers to raise, then assert:

  * Every response carries the X-Request-ID header.
  * Inbound X-Request-ID is echoed (when valid) or replaced (when malformed).
  * ``AppError`` → correct HTTP status + structured envelope with req_id stamp.
  * Unhandled ``Exception`` → 500 INTERNAL envelope (no traceback leak).
  * ``Retry-After`` is set on rate-limit responses.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import AppError
from api.request_context import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    get_request_id,
)


# ---------------------------------------------------------------------------
# Test app fixture — mirror the real main.py wiring but with trivial routes.
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    # Import inside the fixture so we register handlers once per test and
    # don't leak state across tests via a module-level app.
    from main import _app_error_handler, _unhandled_exception_handler

    # Register handlers BEFORE adding middleware / routes so Starlette's
    # ExceptionMiddleware wires them into the stack on first dispatch.
    app = FastAPI(
        exception_handlers={
            AppError: _app_error_handler,
            Exception: _unhandled_exception_handler,
        }
    )
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ok")
    def _ok():
        return {"req_id": get_request_id()}

    @app.get("/boom/rate")
    def _rate():
        raise AppError.rate_limited(retry_after=60)

    @app.get("/boom/unauth")
    def _unauth():
        raise AppError.unauthorized()

    @app.get("/boom/upstream")
    def _upstream():
        raise AppError.upstream_failed(upstream="openai")

    @app.get("/boom/unhandled")
    def _unhandled():
        raise RuntimeError("secret value leaked here")

    # raise_server_exceptions=False so the test client converts unhandled
    # server-side exceptions into a response (letting the handler run) instead
    # of re-raising them into the test body.
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# X-Request-ID header behavior
# ---------------------------------------------------------------------------


class TestRequestIdHeader:
    def test_header_present_on_success(self, client):
        r = client.get("/ok")
        assert r.status_code == 200
        rid = r.headers.get(REQUEST_ID_HEADER)
        assert rid is not None
        uuid.UUID(rid)  # minted UUID
        # And the route body saw the same id.
        assert r.json()["req_id"] == rid

    def test_header_present_on_error(self, client):
        r = client.get("/boom/rate")
        rid = r.headers.get(REQUEST_ID_HEADER)
        assert rid is not None
        # Error body carries the same id so bug reports can correlate.
        assert r.json()["req_id"] == rid

    def test_inbound_uuid_is_echoed(self, client):
        given = str(uuid.uuid4())
        r = client.get("/ok", headers={REQUEST_ID_HEADER: given})
        assert r.headers[REQUEST_ID_HEADER] == given
        assert r.json()["req_id"] == given

    def test_inbound_malformed_is_replaced(self, client):
        r = client.get("/ok", headers={REQUEST_ID_HEADER: "not a uuid"})
        rid = r.headers[REQUEST_ID_HEADER]
        assert rid != "not a uuid"
        uuid.UUID(rid)


# ---------------------------------------------------------------------------
# Error envelope shape
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    def test_rate_limited_is_429_with_retry_after(self, client):
        r = client.get("/boom/rate")
        assert r.status_code == 429
        assert r.headers.get("Retry-After") == "60"
        body = r.json()
        assert body["error_code"] == "rate_limited"
        assert body["message"]
        assert body["req_id"]
        assert body["details"] == {"retry_after": 60}

    def test_unauthorized_is_401(self, client):
        r = client.get("/boom/unauth")
        assert r.status_code == 401
        assert r.json()["error_code"] == "unauthorized"

    def test_upstream_failed_is_503_with_named_upstream(self, client):
        r = client.get("/boom/upstream")
        assert r.status_code == 503
        body = r.json()
        assert body["error_code"] == "upstream_failed"
        assert body["details"] == {"upstream": "openai"}

    def test_unhandled_exception_is_500_without_leaking_message(self, client):
        r = client.get("/boom/unhandled")
        assert r.status_code == 500
        body = r.json()
        assert body["error_code"] == "internal"
        # Generic message — the raw exception args must NEVER reach the client.
        assert "secret value" not in body["message"]
        assert "secret value" not in str(body)
        # But we still stamped a req_id so operators can grep logs.
        assert body["req_id"]
