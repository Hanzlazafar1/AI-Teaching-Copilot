"""Phase 11.7 — centralized, structured, production-grade logging.

One entry point — :func:`configure_logging` — owns every logger used by this
app: our own code, uvicorn's three internal loggers
(``uvicorn``, ``uvicorn.error``, ``uvicorn.access``), and noisy third-party
clients (``httpx``, ``openai``, ``urllib3``). Using
:func:`logging.config.dictConfig` makes the setup declarative, idempotent,
and easy to pass verbatim to uvicorn via its ``log_config=`` parameter
(so uvicorn's own access log gets our formatter).

Three filters are attached to the single stdout handler:

  * ``RequestIdFilter``      — stamps ``req_id`` from the per-request
                                 ContextVar.
  * ``StaticFieldsFilter``   — stamps ``service`` and ``env`` so aggregators
                                 can slice across deployments.
  * ``SecretScrubber``       — redacts known secret shapes (OpenAI API keys,
                                 bearer tokens, JWTs) from message text and
                                 exception tracebacks before they hit disk.

Rules this module enforces:

  * Logging must never raise. Filters swallow exceptions (``return True``)
    so a malformed record can't take down the server.
  * Containerized deploys stream to stdout; the container runtime handles
    rotation. We deliberately do NOT add a FileHandler.
  * No secrets in the log stream. Rendered messages are scrubbed at the
    filter stage (``SecretScrubber``). Exception tracebacks are scrubbed in
    the formatter layer, because ``record.exc_info`` is only rendered to text
    there — BOTH the JSON and plain formatters route that text through the one
    shared ``scrub_text``, so neither can leak a secret. (The filter's own
    ``exc_text`` branch is a backstop only: filters run before the formatter
    populates ``exc_text``, so it is ``None`` at filter time on the normal
    path. See F3.)
"""

from __future__ import annotations

import logging
import logging.config
import re
from typing import Any


# ---------------------------------------------------------------------------
# Secret scrubber
# ---------------------------------------------------------------------------

# Patterns, in priority order. The first match wins for any given region so
# overlapping patterns don't stomp on each other.
#
# Notes:
#   * ``sk-(?:proj-)?[A-Za-z0-9_-]{20,}`` covers both classic OpenAI keys
#     (``sk-…``) and project keys (``sk-proj-…``). The 20-char floor avoids
#     matching benign short strings like ``sk-hello``.
#   * Bearer tokens come from HTTP Authorization headers — we match the full
#     ``Bearer <token>`` phrase so the scrubbed output still reads naturally.
#   * JWTs have three base64url segments joined by dots; the ``eyJ`` prefix
#     is the standard base64-encoded start of ``{"...``.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("bearer",  re.compile(r"(?i)bearer\s+[A-Za-z0-9_.=-]{16,}")),
    ("jwt",     re.compile(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
    )),
)


def scrub_text(text: str) -> str:
    """Redact every known secret shape from ``text`` (idempotent).

    The single source of truth for secret redaction. Reused by three call
    sites so a secret can't slip through whichever layer renders it:
      * :class:`SecretScrubber` — the log filter (rendered message + any
        already-cached ``exc_text``);
      * :class:`api.logging_format.JsonFormatter` — scrubs ``exc_msg`` +
        ``traceback`` built from live ``exc_info`` (see F3);
      * :class:`api.logging_format.ScrubbingPlainFormatter` — scrubs the
        traceback the stdlib appends via ``formatException``.
    """
    for label, pat in _SECRET_PATTERNS:
        text = pat.sub(f"<redacted:{label}>", text)
    return text


# Backward-compatible private alias: pre-F3 code (and existing tests) import
# ``_scrub``. Same function object — ``scrub_text`` is the public name.
_scrub = scrub_text


class SecretScrubber(logging.Filter):
    """Redact known secret shapes from the log record's rendered message.

    Scrubs the rendered message reliably (via :func:`scrub_text`). It also
    scrubs an already-cached ``exc_text`` when one is present, but that is
    only a belt-and-suspenders backstop: on the normal path ``exc_text`` is
    still ``None`` at filter time (the formatter populates it later), so the
    authoritative traceback scrubbing lives in the formatters themselves
    (:class:`api.logging_format.JsonFormatter` and
    :class:`api.logging_format.ScrubbingPlainFormatter`). See F3.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            rendered = record.getMessage()
        except Exception:
            # Logging must never raise. If rendering itself is broken,
            # let the record through untouched so the error surfaces.
            return True

        cleaned = scrub_text(rendered)
        if cleaned != rendered:
            # Replace msg + empty out args so downstream formatters re-render
            # the cleaned string (getMessage() short-circuits when args is
            # empty).
            record.msg = cleaned
            record.args = ()

        if record.exc_text:
            try:
                record.exc_text = scrub_text(record.exc_text)
            except Exception:
                pass

        return True


# ---------------------------------------------------------------------------
# Static fields filter — stamps service + env onto every record
# ---------------------------------------------------------------------------


class StaticFieldsFilter(logging.Filter):
    """Attach ``service`` and ``env`` attributes to every record.

    Both values are strings resolved at configure_logging time from
    :class:`config.Settings`. They become top-level fields in the JSON
    output (:class:`api.logging_format.JsonFormatter` treats them as reserved
    so they always appear with stable placement rather than as merged
    extras).
    """

    def __init__(self, service: str, env: str) -> None:
        super().__init__()
        self.service = service
        self.env = env

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.service = self.service
        record.env = self.env
        return True


# ---------------------------------------------------------------------------
# dictConfig builder
# ---------------------------------------------------------------------------


# Third-party loggers that emit one INFO line per HTTP request. Quieting
# them is the single biggest win for prod log volume. Extend this list if
# a new SDK shows up in the logs spewing at INFO.
_NOISY_THIRD_PARTY = (
    "httpx",
    "httpcore",
    "openai",
    "openai._base_client",
    "urllib3",
    "asyncio",
)


def build_log_config(settings: Any) -> dict[str, Any]:
    """Build the ``logging.config.dictConfig`` dict for the whole app.

    Returned verbatim so callers can also pass it to uvicorn's ``log_config=``
    parameter when launching the server programmatically. That makes
    uvicorn's access/error loggers flow through the same formatter + filters.

    ``disable_existing_loggers=False`` so modules that grabbed a logger
    during import (before this ran) keep working; our explicit loggers
    section re-parents them to the stdout handler either way.
    """
    fmt_name = "json" if str(settings.log_format).lower() == "json" else "plain"
    app_level = str(settings.log_level or "INFO").upper()
    thirdparty_level = str(
        getattr(settings, "log_thirdparty_level", "WARNING") or "WARNING"
    ).upper()
    service = getattr(settings, "log_service_name", "brady-copilot")
    env = getattr(settings, "log_env", "dev")

    third_party_loggers = {
        name: {"level": thirdparty_level, "handlers": ["stdout"], "propagate": False}
        for name in _NOISY_THIRD_PARTY
    }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {
                # Custom factory so the appended exception traceback is
                # scrubbed (the stdlib Formatter renders it inside format(),
                # after the SecretScrubber filter has already run). dictConfig
                # passes ``format``/``datefmt`` through to the Formatter (it
                # retries ``format`` as ``fmt`` for the stdlib signature).
                "()": "api.logging_format.ScrubbingPlainFormatter",
                "format": (
                    "%(asctime)s %(levelname)s %(name)s "
                    "[req_id=%(req_id)s]: %(message)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()": "api.logging_format.JsonFormatter",
            },
        },
        "filters": {
            "req_id": {
                "()": "api.request_context.RequestIdFilter",
            },
            "static_fields": {
                "()": "api.logging_config.StaticFieldsFilter",
                "service": service,
                "env": env,
            },
            "secret_scrubber": {
                "()": "api.logging_config.SecretScrubber",
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": fmt_name,
                "filters": ["secret_scrubber", "static_fields", "req_id"],
            },
        },
        "loggers": {
            # Uvicorn's three internal loggers — own them so uvicorn's own
            # bootstrap doesn't leave them with a non-JSON formatter.
            "uvicorn": {
                "handlers": ["stdout"],
                "level": app_level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["stdout"],
                "level": app_level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["stdout"],
                "level": app_level,
                "propagate": False,
            },
            # Noisy third-party — quiet by default.
            **third_party_loggers,
        },
        "root": {
            "handlers": ["stdout"],
            "level": app_level,
        },
    }


def configure_logging(settings: Any) -> dict[str, Any]:
    """Install the full logging config. Idempotent — safe to call twice
    (on import AND in the lifespan startup hook, e.g., to reclaim uvicorn's
    loggers after its own dictConfig runs).

    Returns the config dict so the caller can pass it to uvicorn via
    ``log_config=…`` when starting the server programmatically.
    """
    config = build_log_config(settings)
    logging.config.dictConfig(config)
    return config
