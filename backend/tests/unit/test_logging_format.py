"""Unit tests for Phase 11.7 (narrow) — JsonFormatter.

Log records are constructed directly rather than captured through a handler
so each test is hermetic — no global logging state to poison other tests,
no dependency on root-logger configuration.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

from api.logging_format import JsonFormatter, ScrubbingPlainFormatter
from api.request_context import reset_request_id, set_request_id


def _record(
    msg: str = "hello",
    level: int = logging.INFO,
    name: str = "test.logger",
    args: tuple = (),
    exc_info=None,
    **extras,
) -> logging.LogRecord:
    """Build a LogRecord matching how ``logger.*`` would produce it, including
    arbitrary ``extra={...}`` kwargs via the ``extras`` map."""
    record = logging.LogRecord(
        name=name, level=level, pathname="x.py", lineno=1,
        msg=msg, args=args, exc_info=exc_info,
    )
    for k, v in extras.items():
        setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# Base record shape
# ---------------------------------------------------------------------------


class TestBaseShape:
    def test_output_is_single_line_json(self):
        out = JsonFormatter().format(_record("hi"))
        assert "\n" not in out  # one line per record
        parsed = json.loads(out)
        assert parsed["msg"] == "hi"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"

    def test_timestamp_is_iso_utc_ms_z(self):
        out = JsonFormatter().format(_record())
        ts = json.loads(out)["ts"]
        # YYYY-MM-DDTHH:MM:SS.mmmZ
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", ts)

    def test_level_name_in_payload(self):
        out = JsonFormatter().format(_record(level=logging.WARNING))
        assert json.loads(out)["level"] == "WARNING"

    def test_message_args_are_applied(self):
        # Mirrors logger.info("%s took %dms", name, ms)
        out = JsonFormatter().format(_record("%s took %dms", args=("QU", 42)))
        assert json.loads(out)["msg"] == "QU took 42ms"


# ---------------------------------------------------------------------------
# Request id integration
# ---------------------------------------------------------------------------


class TestReqIdField:
    def test_req_id_emitted_when_set_on_record(self):
        out = JsonFormatter().format(_record(req_id="abc-123"))
        assert json.loads(out)["req_id"] == "abc-123"

    def test_req_id_omitted_when_empty(self):
        """Record with req_id="" (out-of-request logs) must not emit the
        field. Log aggregators expect absent fields to mean unknown, not
        a magical sentinel like "" that's distinct from "some real id"."""
        out = JsonFormatter().format(_record(req_id=""))
        assert "req_id" not in json.loads(out)

    def test_req_id_omitted_when_missing(self):
        rec = _record()
        # No req_id attribute set.
        out = JsonFormatter().format(rec)
        assert "req_id" not in json.loads(out)


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------


class TestExceptionRendering:
    def test_exc_info_flattened_to_three_fields(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            rec = _record(exc_info=sys.exc_info())
        out = JsonFormatter().format(rec)
        payload = json.loads(out)
        assert payload["exc_type"] == "ValueError"
        assert payload["exc_msg"] == "boom"
        # Traceback is one string (newlines inside it are fine — the outer
        # log line is still one record because we JSON-encoded).
        assert "ValueError: boom" in payload["traceback"]
        assert "Traceback" in payload["traceback"]

    def test_traceback_does_not_break_single_line_output(self):
        """Aggregators that parse NDJSON depend on one record per line.
        Multi-line traceback strings inside the JSON must stay inside
        (JSON encoding escapes the inner newlines)."""
        try:
            raise RuntimeError("x")
        except RuntimeError:
            import sys
            rec = _record(exc_info=sys.exc_info())
        out = JsonFormatter().format(rec)
        assert "\n" not in out  # the OUTER output has no real newlines

    def test_exc_text_cached_traceback_preserved(self):
        """When logging caches exc_text on the record (second format call),
        we still emit it as ``traceback``."""
        rec = _record()
        rec.exc_text = "Traceback (cached)\n  ..."
        out = JsonFormatter().format(rec)
        assert json.loads(out)["traceback"].startswith("Traceback (cached)")

    def test_secret_in_raised_exception_redacted_json(self):
        """F3 regression: a secret embedded in a RAISED exception — both its
        message and the traceback frames — must be redacted by JsonFormatter
        itself.

        This exercises the live ``exc_info`` path: ``exc_text`` is deliberately
        NOT pre-set, because that path never reaches the SecretScrubber filter
        (the filter runs before the formatter populates exc_text, so on the
        JSON path its exc_text branch is dead). ``exc_msg``/``traceback`` are
        derived straight from the exception, so the formatter must scrub them.
        """
        secret = "sk-abcdef1234567890abcdef1234567890"
        try:
            raise ValueError(f"OpenAI rejected key {secret}")
        except ValueError:
            import sys
            rec = _record(exc_info=sys.exc_info())
        assert rec.exc_text is None  # guard: real exc_info path, not cached
        out = JsonFormatter().format(rec)
        payload = json.loads(out)
        # The raw secret must not appear anywhere in the serialized record...
        assert secret not in out
        # ...specifically not in exc_msg or traceback.
        assert secret not in payload["exc_msg"]
        assert secret not in payload["traceback"]
        # ...and the redaction marker IS present in both derived fields.
        assert "<redacted:api_key>" in payload["exc_msg"]
        assert "<redacted:api_key>" in payload["traceback"]
        # Non-secret content preserved — behavior identical otherwise.
        assert payload["exc_type"] == "ValueError"
        assert "OpenAI rejected key" in payload["exc_msg"]

    def test_secret_in_cached_exc_text_redacted_json(self):
        """Defense-in-depth: even when exc_text is pre-populated (e.g. a record
        already formatted by another handler), the JSON formatter re-scrubs it
        rather than trusting an upstream layer to have redacted it."""
        rec = _record()
        rec.exc_text = (
            "Traceback (most recent call last):\n"
            "  AuthenticationError: bad key "
            "sk-abcdef1234567890abcdef1234567890"
        )
        payload = json.loads(JsonFormatter().format(rec))
        assert "sk-abcdef" not in payload["traceback"]
        assert "<redacted:api_key>" in payload["traceback"]


# ---------------------------------------------------------------------------
# Extras merging — logger.*("msg", extra={...})
# ---------------------------------------------------------------------------


class TestExtrasMerging:
    def test_extras_promoted_to_top_level(self):
        out = JsonFormatter().format(
            _record(user_id="u42", latency_ms=87),
        )
        payload = json.loads(out)
        assert payload["user_id"] == "u42"
        assert payload["latency_ms"] == 87

    def test_reserved_key_collision_prefixed_not_dropped(self):
        """If a caller accidentally passes extra={"msg": "x"}, don't silently
        lose it — the reserved key wins but the caller's value survives as
        ``extra_msg``."""
        rec = _record("the real message")
        rec.__dict__["msg"] = "the real message"  # reserved
        # Can't actually shadow msg via _record's setattr because LogRecord
        # sets it in __init__; simulate a collision on another reserved key.
        rec.level = "WARNING"  # "level" is what we emit
        out = JsonFormatter().format(rec)
        payload = json.loads(out)
        # The reserved emitter wins…
        assert payload["level"] == "INFO"
        # …but the caller's value is preserved under extra_*.
        assert payload.get("extra_level") == "WARNING"

    def test_non_json_serializable_extra_falls_back_to_str(self):
        """Rule: logging must NEVER raise. A pydantic model or custom class
        in ``extra`` gets repr'd rather than crashing."""
        class Weird:
            def __repr__(self):
                return "<Weird>"

        out = JsonFormatter().format(_record(obj=Weird()))
        assert "<Weird>" in out  # default=str kicked in

    def test_dunder_extras_skipped(self):
        """Underscore-prefixed attrs are python-internal — don't leak them."""
        rec = _record()
        rec._private = "shhh"  # noqa: SLF001 — deliberate test poke
        out = JsonFormatter().format(rec)
        assert "shhh" not in out


# ---------------------------------------------------------------------------
# Integration: RequestIdFilter + JsonFormatter working together through a
# real StreamHandler. Mirrors main.py's production wiring.
# ---------------------------------------------------------------------------


class TestFilterFormatterIntegration:
    def test_req_id_from_filter_flows_into_json_output(self, caplog):
        import io
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        from api.request_context import RequestIdFilter
        handler.addFilter(RequestIdFilter())

        logger = logging.getLogger("integration.test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        token = set_request_id("req-777")
        try:
            logger.info("hello from a request")
        finally:
            reset_request_id(token)
            logger.removeHandler(handler)

        line = stream.getvalue().strip()
        payload = json.loads(line)
        assert payload["req_id"] == "req-777"
        assert payload["msg"] == "hello from a request"


# ---------------------------------------------------------------------------
# Plain (human-readable) formatter — same secret-in-traceback hardening as the
# JSON path (F3). The stdlib Formatter appends the traceback inside format(),
# after the SecretScrubber filter has run, so it must scrub it itself.
# ---------------------------------------------------------------------------


class TestScrubbingPlainFormatter:
    def test_secret_in_raised_exception_redacted_plain(self):
        """A secret in a RAISED exception must not reach stdout on the plain
        path. Goes through the live ``exc_info`` path (no pre-set exc_text)."""
        secret = "sk-abcdef1234567890abcdef1234567890"
        try:
            raise ValueError(f"key is {secret}")
        except ValueError:
            import sys
            rec = _record(exc_info=sys.exc_info())
        out = ScrubbingPlainFormatter("%(levelname)s %(message)s").format(rec)
        assert secret not in out
        assert "<redacted:api_key>" in out
        # The message body + traceback structure still render.
        assert out.startswith("INFO hello")
        assert "Traceback (most recent call last)" in out
        assert "ValueError" in out

    def test_no_exception_plain_output_identical_to_stdlib(self):
        """Non-exception records format exactly like the stdlib Formatter —
        the override only touches the exception path."""
        rec = _record("plain hello")
        out = ScrubbingPlainFormatter("%(levelname)s %(message)s").format(rec)
        assert out == "INFO plain hello"
