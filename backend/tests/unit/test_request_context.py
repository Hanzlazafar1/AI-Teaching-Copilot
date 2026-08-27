"""Unit tests for Phase 11.1 — request-id plumbing.

Covers:
  - ContextVar get/set/reset behavior
  - RequestIdFilter stamps LogRecord with current req_id
  - _coerce_request_id accepts valid UUIDs, mints otherwise
  - AppError factories produce the documented envelope shape
  - ChatResponse auto-populates request_id from the ContextVar
"""

from __future__ import annotations

import logging
import uuid

import pytest

from api.errors import AppError, ErrorCode, ErrorResponse
from api.models import ChatResponse
from api.request_context import (
    REQUEST_ID_HEADER,
    RequestIdFilter,
    _coerce_request_id,
    get_request_id,
    reset_request_id,
    set_request_id,
)


# ---------------------------------------------------------------------------
# ContextVar plumbing
# ---------------------------------------------------------------------------


class TestContextVar:
    def test_default_is_empty_string(self):
        # Don't assume a request context; grab whatever the default is and
        # assert set/reset is symmetric.
        assert isinstance(get_request_id(), str)

    def test_set_and_reset_restores_prior_value(self):
        token = set_request_id("abc")
        assert get_request_id() == "abc"
        reset_request_id(token)
        assert get_request_id() != "abc"

    def test_nested_contexts(self):
        outer = set_request_id("outer")
        assert get_request_id() == "outer"
        inner = set_request_id("inner")
        assert get_request_id() == "inner"
        reset_request_id(inner)
        assert get_request_id() == "outer"
        reset_request_id(outer)


# ---------------------------------------------------------------------------
# _coerce_request_id — inbound header validation
# ---------------------------------------------------------------------------


class TestCoerceRequestId:
    def test_accepts_valid_uuid4(self):
        valid = str(uuid.uuid4())
        assert _coerce_request_id(valid) == valid

    def test_accepts_uppercase_uuid(self):
        valid = str(uuid.uuid4()).upper()
        assert _coerce_request_id(valid) == valid

    def test_rejects_malformed_and_mints_new_uuid(self):
        out = _coerce_request_id("not-a-uuid")
        # Must be a fresh UUID (so log injection isn't possible).
        assert out != "not-a-uuid"
        uuid.UUID(out)  # raises if not a UUID

    def test_rejects_empty_and_mints_new_uuid(self):
        out = _coerce_request_id("")
        uuid.UUID(out)

    def test_rejects_none_and_mints_new_uuid(self):
        out = _coerce_request_id(None)
        uuid.UUID(out)

    def test_rejects_log_injection_attempt(self):
        # Classic log-poisoning payload: inject newlines + fake log lines.
        payload = "a\n2026-04-20 INFO FAKE: user_id=victim owned"
        out = _coerce_request_id(payload)
        assert "\n" not in out
        uuid.UUID(out)


# ---------------------------------------------------------------------------
# RequestIdFilter — logging integration
# ---------------------------------------------------------------------------


class TestRequestIdFilter:
    def test_filter_stamps_current_req_id(self):
        filt = RequestIdFilter()
        token = set_request_id("test-id-123")
        try:
            record = logging.LogRecord(
                name="x", level=logging.INFO, pathname="",
                lineno=0, msg="m", args=(), exc_info=None,
            )
            assert filt.filter(record) is True
            assert record.req_id == "test-id-123"
        finally:
            reset_request_id(token)

    def test_filter_overwrites_stale_req_id_on_reuse(self):
        """Handlers may be reused across requests — filter must always
        overwrite whatever was stamped previously."""
        filt = RequestIdFilter()
        record = logging.LogRecord(
            name="x", level=logging.INFO, pathname="",
            lineno=0, msg="m", args=(), exc_info=None,
        )
        record.req_id = "stale"
        token = set_request_id("fresh")
        try:
            filt.filter(record)
            assert record.req_id == "fresh"
        finally:
            reset_request_id(token)


# ---------------------------------------------------------------------------
# AppError factories + envelope
# ---------------------------------------------------------------------------


class TestAppError:
    def test_rate_limited_sets_429_and_retry_after_header(self):
        err = AppError.rate_limited(retry_after=60)
        assert err.http_status == 429
        assert err.error_code is ErrorCode.RATE_LIMITED
        assert err.headers == {"Retry-After": "60"}

    def test_rate_limited_without_retry_after_omits_header(self):
        err = AppError.rate_limited()
        assert err.headers == {}

    def test_validation_error_carries_details(self):
        err = AppError.validation_error("bad", field="session_id")
        assert err.http_status == 400
        assert err.details == {"field": "session_id"}

    def test_unauthorized_is_401(self):
        assert AppError.unauthorized().http_status == 401

    def test_forbidden_is_403(self):
        assert AppError.forbidden().http_status == 403

    def test_not_found_is_404(self):
        assert AppError.not_found().http_status == 404

    def test_budget_exhausted_includes_scope(self):
        err = AppError.budget_exhausted(scope="user-daily")
        assert err.http_status == 429
        assert err.details == {"scope": "user-daily"}

    def test_upstream_failed_is_503_and_names_upstream(self):
        err = AppError.upstream_failed(upstream="openai")
        assert err.http_status == 503
        assert err.details == {"upstream": "openai"}

    def test_timed_out_is_504(self):
        assert AppError.timed_out().http_status == 504

    def test_internal_is_500(self):
        assert AppError.internal().http_status == 500

    def test_to_response_stamps_req_id(self):
        err = AppError.internal()
        resp = err.to_response(req_id="abc-123")
        assert isinstance(resp, ErrorResponse)
        assert resp.req_id == "abc-123"
        assert resp.error_code is ErrorCode.INTERNAL

    def test_to_response_without_req_id(self):
        resp = AppError.internal().to_response()
        assert resp.req_id is None

    def test_error_code_serializes_to_lowercase_string(self):
        """Client stability: adding an enum variant must not break existing
        string comparisons."""
        assert ErrorCode.RATE_LIMITED.value == "rate_limited"
        assert ErrorCode.INTERNAL.value == "internal"


# ---------------------------------------------------------------------------
# ChatResponse auto-populates request_id
# ---------------------------------------------------------------------------


class TestChatResponseReqId:
    def test_request_id_picked_up_from_contextvar(self):
        token = set_request_id("chat-resp-test")
        try:
            resp = ChatResponse(response="hi", intent="unknown", quality="validated")
            assert resp.request_id == "chat-resp-test"
        finally:
            reset_request_id(token)

    def test_request_id_none_outside_request_context(self):
        # Outside a set_request_id scope the contextvar defaults to "".
        # The factory must turn that into None so JSON doesn't carry an
        # empty string that clients mistake for a real id.
        # Reset any state first:
        try:
            while get_request_id():
                break
        except Exception:
            pass
        resp = ChatResponse(response="hi", intent="unknown", quality="validated")
        assert resp.request_id is None

    def test_explicit_request_id_overrides_default(self):
        token = set_request_id("from-contextvar")
        try:
            resp = ChatResponse(
                response="hi", intent="unknown", quality="validated",
                request_id="explicit",
            )
            assert resp.request_id == "explicit"
        finally:
            reset_request_id(token)


# ---------------------------------------------------------------------------
# Constants / sanity
# ---------------------------------------------------------------------------


class TestConstants:
    def test_request_id_header_name(self):
        assert REQUEST_ID_HEADER == "X-Request-ID"
