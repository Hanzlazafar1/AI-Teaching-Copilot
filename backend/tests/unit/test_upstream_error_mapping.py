"""Unit tests for Phase 11.11 — OpenAI / httpx / timeout error mapping.

When something below the route handler raises an ``openai.APIError``, an
``httpx.HTTPError``, or an ``asyncio.TimeoutError``, the global exception
handlers in ``main.py`` must translate them into the appropriate structured
envelope (503 / 504 with the correct ``error_code``) — NOT a 500 INTERNAL.
This is the difference between "OpenAI had a hiccup, retry in a few seconds"
and "the server is broken, file a bug."

Tests spin up a minimal FastAPI app with the real handlers registered and
raise each exception type from a trivial route to assert the mapping.
"""

from __future__ import annotations

import asyncio

import httpx
import openai
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import AppError
from api.request_context import RequestIdMiddleware


@pytest.fixture
def client() -> TestClient:
    from main import (
        _app_error_handler,
        _asyncio_timeout_handler,
        _httpx_error_handler,
        _httpx_timeout_handler,
        _openai_api_handler,
        _openai_auth_handler,
        _openai_timeout_handler,
        _unhandled_exception_handler,
    )

    # Register the same set of exception handlers the real app uses. Order
    # matters only for MRO resolution — the more-specific APITimeoutError
    # wins over the broader APIError because Starlette walks __mro__.
    app = FastAPI(
        exception_handlers={
            AppError: _app_error_handler,
            openai.APITimeoutError: _openai_timeout_handler,
            openai.AuthenticationError: _openai_auth_handler,
            openai.APIError: _openai_api_handler,
            httpx.TimeoutException: _httpx_timeout_handler,
            httpx.HTTPError: _httpx_error_handler,
            asyncio.TimeoutError: _asyncio_timeout_handler,
            Exception: _unhandled_exception_handler,
        }
    )
    app.add_middleware(RequestIdMiddleware)

    # Stubs to simulate each failure. We construct the SDK exceptions with
    # whatever minimum arguments they require — we don't care about their
    # content, only about the class identity for MRO dispatch.
    dummy_request = httpx.Request("POST", "https://api.openai.com/v1/x")

    @app.get("/boom/openai-timeout")
    def _openai_timeout():
        raise openai.APITimeoutError(request=dummy_request)

    @app.get("/boom/openai-connection")
    def _openai_connection():
        raise openai.APIConnectionError(request=dummy_request)

    @app.get("/boom/openai-auth")
    def _openai_auth():
        # AuthenticationError's signature varies; construct the simplest form.
        raise openai.AuthenticationError(
            message="invalid key",
            response=httpx.Response(401, request=dummy_request),
            body=None,
        )

    @app.get("/boom/openai-rate")
    def _openai_rate():
        raise openai.RateLimitError(
            message="rate limit",
            response=httpx.Response(429, request=dummy_request),
            body=None,
        )

    @app.get("/boom/httpx-timeout")
    def _httpx_timeout():
        raise httpx.ReadTimeout("read timed out", request=dummy_request)

    @app.get("/boom/httpx-connect")
    def _httpx_connect():
        raise httpx.ConnectError("refused", request=dummy_request)

    @app.get("/boom/asyncio-timeout")
    def _asyncio_timeout():
        raise asyncio.TimeoutError()

    @app.get("/boom/other")
    def _other():
        raise ValueError("something went wrong")

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# OpenAI-specific mappings
# ---------------------------------------------------------------------------


class TestOpenAIErrorMapping:
    def test_openai_timeout_maps_to_504(self, client):
        r = client.get("/boom/openai-timeout")
        assert r.status_code == 504
        assert r.json()["error_code"] == "timed_out"

    def test_openai_connection_maps_to_503(self, client):
        r = client.get("/boom/openai-connection")
        assert r.status_code == 503
        body = r.json()
        assert body["error_code"] == "upstream_failed"
        assert body["details"] == {"upstream": "openai"}

    def test_openai_rate_limit_from_upstream_maps_to_503_not_429(self, client):
        """OpenAI saying *they* are rate-limited is an upstream issue for us;
        the 429 the CLIENT sees from OUR API is reserved for *our* per-user
        rate limit. Mixing them would confuse clients about who to back off."""
        r = client.get("/boom/openai-rate")
        assert r.status_code == 503
        assert r.json()["error_code"] == "upstream_failed"

    def test_openai_auth_error_is_500_not_503(self, client):
        """OpenAI rejected our API key → server misconfiguration, not
        retry-worthy for the client."""
        r = client.get("/boom/openai-auth")
        assert r.status_code == 500
        assert r.json()["error_code"] == "internal"
        # And critically — don't leak the OpenAI error message (could include
        # an API key prefix or similar).
        assert "invalid key" not in r.text


# ---------------------------------------------------------------------------
# httpx-level mappings (for embedding calls that bypass openai SDK)
# ---------------------------------------------------------------------------


class TestHttpxErrorMapping:
    def test_httpx_read_timeout_maps_to_504(self, client):
        r = client.get("/boom/httpx-timeout")
        assert r.status_code == 504
        assert r.json()["error_code"] == "timed_out"

    def test_httpx_connect_error_maps_to_503(self, client):
        r = client.get("/boom/httpx-connect")
        assert r.status_code == 503
        body = r.json()
        assert body["error_code"] == "upstream_failed"
        assert body["details"] == {"upstream": "httpx"}


# ---------------------------------------------------------------------------
# asyncio timeout + catch-all
# ---------------------------------------------------------------------------


class TestGenericTimeoutAndCatchAll:
    def test_asyncio_timeout_maps_to_504(self, client):
        r = client.get("/boom/asyncio-timeout")
        assert r.status_code == 504
        assert r.json()["error_code"] == "timed_out"

    def test_non_upstream_exception_still_500(self, client):
        """Our mappings should NOT steal routes for unrelated exceptions —
        a plain ValueError must still fall through to the catch-all 500."""
        r = client.get("/boom/other")
        assert r.status_code == 500
        assert r.json()["error_code"] == "internal"


# ---------------------------------------------------------------------------
# req_id correlation preserved across the new handlers
# ---------------------------------------------------------------------------


class TestReqIdStampedOnUpstreamErrors:
    def test_upstream_error_carries_req_id(self, client):
        r = client.get("/boom/openai-timeout")
        assert r.headers.get("X-Request-ID")
        assert r.json()["req_id"] == r.headers["X-Request-ID"]

    def test_client_supplied_req_id_echoed_through_upstream_error(self, client):
        import uuid as _uuid
        given = str(_uuid.uuid4())
        r = client.get(
            "/boom/httpx-connect",
            headers={"X-Request-ID": given},
        )
        assert r.headers["X-Request-ID"] == given
        assert r.json()["req_id"] == given
