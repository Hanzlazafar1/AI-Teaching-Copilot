"""Application configuration via environment variables.

Loaded from ``.env`` in dev and from the process environment in production
(see ``.env.example`` for the full variable inventory). Required secrets are
validated at import time by :func:`_validate_required_secrets` — a missing or
empty value crashes the server on startup rather than failing silently on the
first API call. That fail-fast behavior is what lets a container orchestrator
(Kubernetes, ECS, Docker Compose) surface a clear "config broken" signal
instead of a health-check heartbeat followed by opaque 500s.

For production deployment, inject secrets via your secret manager of choice
(Doppler, AWS Secrets Manager, HashiCorp Vault, Kubernetes secrets) — the
container runtime sets them as environment variables before ``uvicorn`` runs.
Do NOT ship real secrets in a committed ``.env`` file.
"""

from __future__ import annotations

import os
import sys

from pydantic_settings import BaseSettings


class MissingSecretError(RuntimeError):
    """Raised on import if a required secret is missing or empty.

    Separate exception class so deployment scripts / smoke tests can catch it
    specifically without also catching unrelated :class:`RuntimeError`.
    """


# Required secrets — missing or whitespace-only values cause a fail-fast at
# import. Additive-only: removing an entry is a breaking change for deploy
# scripts that verify the list.
_REQUIRED_SECRETS: tuple[str, ...] = (
    "openai_api_key",
)


class Settings(BaseSettings):
    """Centralized settings loaded from .env with sensible defaults."""

    # --- OpenAI / OpenRouter ---
    openai_api_key: str = ""
    openai_base_url: str = ""  # Set to https://openrouter.ai/api/v1 for OpenRouter
    openai_generation_model: str = "gpt-5.4"
    openai_judge_model: str = "gpt-5.4-mini"
    openai_query_model: str = "gpt-5.4-mini"
    openai_embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072

    # --- Validation ---
    judge_score_threshold: float = 85.0
    max_generation_attempts: int = 3
    generation_temperatures: list[float] = [0.3, 0.4, 0.5]
    # Budget: 3 full generation attempts (~12s each) + 3 judge calls (~5s)
    # + optional repair pass (~4s) + ~10s reserve. 90s gives headroom for
    # the repair path (Phase 11.9) without clipping the judge on the main
    # retry loop.
    route_timeout_seconds: float = 90.0
    quality_floor_score: float = 40.0

    # --- Retrieval ---
    retrieval_top_k_lesson: int = 10
    retrieval_top_k_coaching: int = 8
    context_token_budget: int = 10000
    min_results_before_relaxation: int = 5

    # --- API ---
    log_level: str = "INFO"
    # "plain" (default, human-readable) or "json" (one-line JSON per record,
    # indexable by log aggregators). Toggle via LOG_FORMAT env var —
    # recommended: plain for local dev, json for production container logs.
    log_format: str = "plain"
    # Static fields stamped onto every log record so aggregators can filter
    # across services / environments without parsing log message text.
    log_service_name: str = "brady-copilot"
    log_env: str = "dev"  # "dev" | "staging" | "prod" (or whatever convention)
    # Noisy third-party libraries (httpx, openai, urllib3) log every HTTP
    # request at INFO by default — overwhelming at prod scale. Default WARNING
    # keeps their errors/warnings without drowning our app's own logs.
    log_thirdparty_level: str = "WARNING"
    max_query_length: int = 2000
    rate_limit_per_hour: int = 50
    cors_origins: list[str] = [
        "http://localhost:3000",
        "https://brady-learnsworld-lms.vercel.app",
    ]

    # --- Paths ---
    chunks_dir: str = "chunks"
    qdrant_path: str = "qdrant_data"
    framework_chunks_file: str = "chunks/01-master-4step.json"

    # --- Excluded chunk files (skip during ingestion) ---
    ingest_exclude_files: list[str] = [
        "01-master-4step.json",  # loaded at startup into system prompt
    ]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


def _validate_required_secrets(s: Settings) -> None:
    """Crash at import time when a required secret is missing or empty.

    Fail-fast is deliberate: in production the orchestrator's "container is
    healthy" heartbeat should reflect real readiness. A silently-empty API
    key leads to cryptic upstream-auth failures at first traffic — crashing
    at startup converts that into an immediate, actionable error.

    Exception is :class:`MissingSecretError` (subclass of RuntimeError) so
    deploy tooling can target it specifically.
    """
    # Some test invocations (pure unit tests that never touch an LLM) may
    # legitimately run without secrets. Honor an explicit escape hatch so the
    # fail-fast doesn't block them. ``pytest`` sets this automatically via
    # conftest when appropriate.
    if os.environ.get("COPILOT_SKIP_SECRET_VALIDATION") == "1":
        return

    missing: list[str] = []
    for name in _REQUIRED_SECRETS:
        raw = getattr(s, name, "")
        if not raw or not str(raw).strip():
            # Report the env-var form (uppercase) since that's what operators
            # set in their deploy tooling.
            missing.append(name.upper())

    if missing:
        msg = (
            "Missing or empty required secret(s): "
            + ", ".join(missing)
            + ". Set them in your .env (dev) or via your secret manager "
            "(production). See .env.example for the full inventory."
        )
        raise MissingSecretError(msg)


# The OpenAI / httpx SDKs read OPENAI_BASE_URL directly from the process
# environment, even when our own client constructors skip passing an empty
# base_url. An empty value (e.g. `OPENAI_BASE_URL=` in .env) is honored as
# "use empty base URL" and produces httpx UnsupportedProtocol errors on the
# very first call. Treat empty/whitespace as "unset" so the SDK falls back to
# api.openai.com. Run this BEFORE Settings() so pydantic doesn't load the
# broken value.
if not (os.environ.get("OPENAI_BASE_URL") or "").strip():
    os.environ.pop("OPENAI_BASE_URL", None)


settings = Settings()
_validate_required_secrets(settings)
