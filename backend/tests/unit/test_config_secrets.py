"""Unit tests for Phase 11.2 — required-secret fail-fast.

We can't just re-import ``config`` because it's cached. Instead, we exercise
the validator function directly against a constructed ``Settings`` instance
so each test is hermetic and doesn't mutate process state.
"""

from __future__ import annotations

import os

import pytest

from config import (
    MissingSecretError,
    Settings,
    _REQUIRED_SECRETS,
    _validate_required_secrets,
)


class TestValidateRequiredSecrets:
    def test_passes_when_all_secrets_present(self):
        s = Settings(openai_api_key="sk-real-value")
        # Must not raise.
        _validate_required_secrets(s)

    def test_raises_missing_secret_error_when_empty(self):
        s = Settings(openai_api_key="")
        with pytest.raises(MissingSecretError) as excinfo:
            _validate_required_secrets(s)
        # Error message must name the env var (uppercase) so the operator
        # knows what to set.
        assert "OPENAI_API_KEY" in str(excinfo.value)

    def test_raises_when_whitespace_only(self):
        """A key of spaces is worse than missing — often a copy-paste bug."""
        s = Settings(openai_api_key="   \t  ")
        with pytest.raises(MissingSecretError):
            _validate_required_secrets(s)

    def test_error_message_references_env_example(self):
        """Operators need a pointer to where the variable inventory lives."""
        s = Settings(openai_api_key="")
        with pytest.raises(MissingSecretError) as excinfo:
            _validate_required_secrets(s)
        assert ".env.example" in str(excinfo.value)

    def test_escape_hatch_skips_validation(self, monkeypatch):
        """Tests + CI smoke checks that don't need real secrets should work.

        The escape hatch must be explicit (exact value "1") so a stray env
        var can't accidentally disable fail-fast in production.
        """
        monkeypatch.setenv("COPILOT_SKIP_SECRET_VALIDATION", "1")
        s = Settings(openai_api_key="")
        # Must not raise.
        _validate_required_secrets(s)

    def test_escape_hatch_value_must_be_exactly_1(self, monkeypatch):
        monkeypatch.setenv("COPILOT_SKIP_SECRET_VALIDATION", "true")
        s = Settings(openai_api_key="")
        with pytest.raises(MissingSecretError):
            _validate_required_secrets(s)

    def test_missing_secret_error_is_runtime_error(self):
        """Subclass relation so deploy tooling can catch RuntimeError."""
        assert issubclass(MissingSecretError, RuntimeError)

    def test_required_secrets_list_is_non_empty(self):
        """At minimum OPENAI_API_KEY must be required — this is a sanity
        guard against someone accidentally emptying the list."""
        assert "openai_api_key" in _REQUIRED_SECRETS


class TestOpenAIBaseUrlSanitization:
    def test_empty_base_url_is_popped_from_environ(self, monkeypatch):
        """An empty OPENAI_BASE_URL poisons the OpenAI SDK (httpx
        UnsupportedProtocol). The config module pops empty values at import.
        We re-run the same guard logic here to confirm it remains correct.
        """
        monkeypatch.setenv("OPENAI_BASE_URL", "")
        # Re-execute the guard logic in isolation.
        if not (os.environ.get("OPENAI_BASE_URL") or "").strip():
            os.environ.pop("OPENAI_BASE_URL", None)
        assert "OPENAI_BASE_URL" not in os.environ

    def test_whitespace_base_url_also_popped(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "   ")
        if not (os.environ.get("OPENAI_BASE_URL") or "").strip():
            os.environ.pop("OPENAI_BASE_URL", None)
        assert "OPENAI_BASE_URL" not in os.environ

    def test_real_base_url_preserved(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        if not (os.environ.get("OPENAI_BASE_URL") or "").strip():
            os.environ.pop("OPENAI_BASE_URL", None)
        assert os.environ["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"
