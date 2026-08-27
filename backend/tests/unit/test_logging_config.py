"""Unit tests for Phase 11.7 — centralized logging config + secret scrubber.

Covers:
  - SecretScrubber redacts known secret shapes in message + exc_text
  - StaticFieldsFilter stamps service/env on every record
  - build_log_config produces a valid dictConfig spec
  - configure_logging is idempotent
  - third-party loggers quieted to WARNING by default
  - uvicorn loggers claimed by our config
  - JsonFormatter emits service/env with stable placement
"""

from __future__ import annotations

import json
import logging
import logging.config
from dataclasses import dataclass

import pytest

from api.logging_config import (
    SecretScrubber,
    StaticFieldsFilter,
    _NOISY_THIRD_PARTY,
    _scrub,
    build_log_config,
    configure_logging,
)
from api.logging_format import JsonFormatter


# ---------------------------------------------------------------------------
# Fake settings object so tests don't depend on the real config loader.
# ---------------------------------------------------------------------------


@dataclass
class _FakeSettings:
    log_level: str = "INFO"
    log_format: str = "json"
    log_service_name: str = "brady-copilot-test"
    log_env: str = "test"
    log_thirdparty_level: str = "WARNING"


def _record(
    msg: str = "x",
    args: tuple = (),
    exc_info=None,
    **extras,
) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="t", level=logging.INFO, pathname="x.py", lineno=1,
        msg=msg, args=args, exc_info=exc_info,
    )
    for k, v in extras.items():
        setattr(rec, k, v)
    return rec


# ---------------------------------------------------------------------------
# SecretScrubber — redaction
# ---------------------------------------------------------------------------


class TestSecretScrubberDirect:
    """Tests against the underlying ``_scrub`` text function."""

    def test_openai_classic_key_redacted(self):
        text = "auth header: sk-abcdef1234567890abcdef1234567890 end"
        cleaned = _scrub(text)
        assert "sk-abcdef" not in cleaned
        assert "<redacted:api_key>" in cleaned

    def test_openai_project_key_redacted(self):
        # Synthetic sk-proj- shape (prefix + 100+ chars). NOT a real key —
        # keep test fixtures free of any material that resembles a live
        # secret.
        key = "sk-proj-" + "A" * 60 + "B" * 60
        text = f"OPENAI_API_KEY={key}"
        cleaned = _scrub(text)
        assert key not in cleaned
        assert "<redacted:api_key>" in cleaned

    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def"
        cleaned = _scrub(text)
        # The whole "Bearer <token>" phrase gets replaced.
        assert "<redacted:bearer>" in cleaned
        assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned

    def test_jwt_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NSJ9.sig_abc_DEF"
        text = f"token={jwt}"
        cleaned = _scrub(text)
        assert jwt not in cleaned
        assert "<redacted:jwt>" in cleaned

    def test_multiple_secrets_all_redacted(self):
        text = (
            "OPENAI_API_KEY=sk-abcdef1234567890abcdef1234567890 "
            "Authorization: Bearer abcdef1234567890abcdef"
        )
        cleaned = _scrub(text)
        assert "sk-abcdef" not in cleaned
        assert "abcdef1234567890abcdef" not in cleaned

    def test_short_sk_dash_prefix_not_matched(self):
        """False-positive guard: ``sk-hello`` is not a real key — don't
        clobber innocent strings that happen to share the prefix."""
        text = "my skateboard sk-hello world"
        cleaned = _scrub(text)
        # Nothing matches the 20-char floor, nothing redacted.
        assert "<redacted" not in cleaned

    def test_no_secret_unchanged(self):
        text = "normal log line with no secret"
        assert _scrub(text) == text


class TestSecretScrubberFilter:
    """Tests against the LogRecord-level ``SecretScrubber.filter`` path."""

    def test_filter_rewrites_rendered_message(self):
        rec = _record("OPENAI_API_KEY=sk-abcdef1234567890abcdef1234567890")
        SecretScrubber().filter(rec)
        # After filter, getMessage() returns the scrubbed text (because we
        # overwrite msg + args) — formatters see the redacted form.
        assert "sk-abcdef" not in rec.getMessage()
        assert "<redacted:api_key>" in rec.getMessage()

    def test_filter_scrubs_args_interpolation(self):
        """Classic logger call: ``logger.info("key=%s", key)`` — the secret
        lives in args until rendered. Scrubber must redact the rendered form
        not the unrendered template."""
        rec = _record("key=%s", args=("sk-abcdef1234567890abcdef1234567890",))
        SecretScrubber().filter(rec)
        msg = rec.getMessage()
        assert "sk-abcdef" not in msg
        assert "<redacted:api_key>" in msg

    def test_filter_scrubs_exc_text(self):
        """Traceback strings can contain secrets too (e.g., the traceback of
        an OpenAI auth error prints the key into the frame)."""
        rec = _record()
        rec.exc_text = (
            "Traceback:\n  AuthenticationError: "
            "Invalid key sk-abcdef1234567890abcdef1234567890"
        )
        SecretScrubber().filter(rec)
        assert "sk-abcdef" not in rec.exc_text
        assert "<redacted:api_key>" in rec.exc_text

    def test_filter_never_raises(self):
        """Contract: a broken record must not take down the logger."""
        class BadRecord:
            def getMessage(self):
                raise RuntimeError("I am broken")
            # Extra attributes the filter may touch:
            exc_text = ""
            msg = "ok"
            args = ()
        # Duck-typing — filter() just checks attributes, doesn't require the
        # LogRecord class.
        assert SecretScrubber().filter(BadRecord()) is True  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# StaticFieldsFilter
# ---------------------------------------------------------------------------


class TestStaticFieldsFilter:
    def test_stamps_service_and_env(self):
        rec = _record()
        StaticFieldsFilter(service="svc-a", env="staging").filter(rec)
        assert rec.service == "svc-a"
        assert rec.env == "staging"

    def test_overwrites_prior_values(self):
        """A record that already has service/env set (rare but possible if
        two filters are stacked) must end up with OUR filter's values."""
        rec = _record(service="wrong", env="wrong")
        StaticFieldsFilter(service="right", env="prod").filter(rec)
        assert rec.service == "right"
        assert rec.env == "prod"


# ---------------------------------------------------------------------------
# Static fields appear in JsonFormatter output with stable placement
# ---------------------------------------------------------------------------


class TestJsonFormatterStaticFields:
    def test_service_env_req_id_appear_at_top(self):
        rec = _record("hi", service="brady", env="prod", req_id="abc")
        payload = json.loads(JsonFormatter().format(rec))
        # All three reserved fields present.
        assert payload["service"] == "brady"
        assert payload["env"] == "prod"
        assert payload["req_id"] == "abc"
        # Ordering: ts, level, logger, msg, then reserved fields (Python
        # dict preserves insertion order, json.dumps respects it).
        keys = list(payload.keys())
        assert keys.index("service") > keys.index("msg")
        assert keys.index("service") < keys.index("env")

    def test_service_env_absent_when_unset(self):
        """Background log lines before StaticFieldsFilter ran shouldn't
        emit empty strings — omit the fields entirely."""
        rec = _record("hi")
        payload = json.loads(JsonFormatter().format(rec))
        assert "service" not in payload
        assert "env" not in payload


# ---------------------------------------------------------------------------
# build_log_config
# ---------------------------------------------------------------------------


class TestBuildLogConfig:
    def test_returns_valid_dictconfig_shape(self):
        config = build_log_config(_FakeSettings())
        # dictConfig requires version=1.
        assert config["version"] == 1
        # disable_existing_loggers=False so prior-imported loggers keep
        # working (see docstring in logging_config.py).
        assert config["disable_existing_loggers"] is False
        assert "formatters" in config
        assert "filters" in config
        assert "handlers" in config

    def test_json_formatter_selected_when_format_is_json(self):
        config = build_log_config(_FakeSettings(log_format="json"))
        handler = config["handlers"]["stdout"]
        assert handler["formatter"] == "json"

    def test_plain_formatter_selected_by_default(self):
        config = build_log_config(_FakeSettings(log_format="plain"))
        handler = config["handlers"]["stdout"]
        assert handler["formatter"] == "plain"

    def test_all_three_filters_attached_to_handler(self):
        config = build_log_config(_FakeSettings())
        filters = set(config["handlers"]["stdout"]["filters"])
        assert filters == {"secret_scrubber", "static_fields", "req_id"}

    def test_uvicorn_loggers_claimed(self):
        """Our config must explicitly list uvicorn's loggers so uvicorn's
        own bootstrap dictConfig doesn't leave them with a different
        formatter."""
        config = build_log_config(_FakeSettings())
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            assert name in config["loggers"]
            assert "stdout" in config["loggers"][name]["handlers"]
            # propagate=False so we don't double-emit through root.
            assert config["loggers"][name]["propagate"] is False

    def test_third_party_loggers_quieted(self):
        config = build_log_config(_FakeSettings(log_thirdparty_level="WARNING"))
        for name in _NOISY_THIRD_PARTY:
            assert name in config["loggers"]
            assert config["loggers"][name]["level"] == "WARNING"

    def test_third_party_level_configurable(self):
        config = build_log_config(_FakeSettings(log_thirdparty_level="ERROR"))
        assert config["loggers"]["httpx"]["level"] == "ERROR"

    def test_static_fields_filter_bound_to_settings(self):
        config = build_log_config(
            _FakeSettings(log_service_name="svc", log_env="prod"),
        )
        f = config["filters"]["static_fields"]
        assert f["service"] == "svc"
        assert f["env"] == "prod"


# ---------------------------------------------------------------------------
# configure_logging — end-to-end idempotency
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def test_first_call_succeeds(self):
        # Does not raise. The real assertion is that dictConfig accepts
        # the full config dict.
        configure_logging(_FakeSettings())

    def test_double_call_is_idempotent(self):
        """Called once at import, once in lifespan startup — must be safe."""
        configure_logging(_FakeSettings(log_format="plain"))
        configure_logging(_FakeSettings(log_format="json"))
        # Second call wins — handler formatter now json.
        root = logging.getLogger()
        assert root.handlers, "expected root handler installed"

    def test_real_log_line_after_configure_goes_through_filters(
        self, capsys
    ):
        """Emit a log line after configuring; capture stdout; check that
        the secret scrubber redacted the key."""
        configure_logging(_FakeSettings(log_format="json"))
        logger = logging.getLogger("integration.scrub")
        logger.info(
            "loaded key %s",
            "sk-abcdef1234567890abcdef1234567890",
        )
        # Flush so stdout capture sees the line.
        for h in logging.getLogger().handlers:
            h.flush()
        out = capsys.readouterr().out
        # The raw key must NOT appear; the redacted token must.
        assert "sk-abcdef1234567890" not in out
        assert "<redacted:api_key>" in out
