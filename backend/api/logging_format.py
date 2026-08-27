"""Phase 11.7 (narrow scope) — structured JSON log formatter.

Emits one JSON object per log record so log aggregators (Loki, CloudWatch,
Datadog, ELK) can index fields directly instead of regex-parsing plaintext.

Selected by ``LOG_FORMAT=json`` env var (``config.Settings.log_format``);
default ``plain`` preserves the human-readable format for local dev so
``tail -f uvicorn.log`` stays skimmable.

Record shape:
    { "ts":     "2026-04-20T18:42:59.123Z",  // UTC, Z-suffixed, ms precision
      "level":  "INFO",
      "logger": "query.understanding",
      "msg":    "Query understood: type=SCRIPTED_ML ...",
      "req_id": "a0b627e1-...-3bb7470a0789"  // omitted when empty
      // on errors:
      "exc_type":  "ValueError",
      "exc_msg":   "something went wrong",
      "traceback": "Traceback (most recent call last):\\n  File ..."
      // any logger.*(msg, extra={...}) keys are merged at top level
    }

The whole record is serialized with ``separators=(",", ":")`` — no leading
whitespace, no trailing newline except the one ``logging.StreamHandler`` adds
— so each line is one self-contained record. Unserializable extras fall back
to ``repr(value)`` so one weird ``extra={"obj": some_instance}`` can't crash
the logger (rule: logging must never raise).
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone

from api.logging_config import scrub_text


# LogRecord attributes set by ``logging`` itself — every other key in
# ``record.__dict__`` came from ``extra={...}`` and should be merged into the
# output. Taken from the Python 3.10 logging source + our own filters
# (RequestIdFilter, StaticFieldsFilter).
_STANDARD_LOGRECORD_ATTRS: frozenset[str] = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "asctime", "message",
    # Project-specific — rendered as top-level fields with stable placement
    # near the top of the payload, not as anonymous merged extras.
    "req_id",
    "service",
    "env",
    # Third-party framework attributes we don't want bleeding into the
    # structured payload. ``color_message`` is uvicorn's ANSI-colored
    # internal variant of the plain ``msg`` — redundant with ``msg`` and
    # ugly in JSON.
    "color_message",
})


class JsonFormatter(logging.Formatter):
    """One-line JSON output per record.

    Keeps the base ``Formatter`` contract (``.format(record) -> str``) so it
    drops into any standard ``StreamHandler`` / ``FileHandler`` without
    changing downstream code.
    """

    # UTC timestamp with milliseconds — isoformat() + Z suffix. Seconds-only
    # is too coarse for ordering logs during a burst; nanoseconds is overkill.
    def _timestamp(self, record: logging.LogRecord) -> str:
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self._timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Reserved fields — emit early (near the top of the JSON payload)
        # and only when non-empty so background / import-time logs don't
        # carry meaningless empty strings. StaticFieldsFilter supplies
        # service + env; RequestIdFilter supplies req_id.
        for field in ("service", "env", "req_id"):
            val = getattr(record, field, "") or ""
            if val:
                payload[field] = val

        # Exception info — collapsed into one string so log aggregators don't
        # split it across multiple records (and on-call can grep the type).
        if record.exc_info:
            exc_type, exc_val, exc_tb = record.exc_info
            payload["exc_type"] = getattr(exc_type, "__name__", repr(exc_type))
            # exc_msg + traceback are derived straight from the live exception,
            # so they never passed through the SecretScrubber filter (the
            # filter only sees the rendered message, and its exc_text branch is
            # dead on this path because we never populate exc_text). Scrub them
            # at the point of emission through the one shared redactor. See F3.
            payload["exc_msg"] = scrub_text(str(exc_val))
            payload["traceback"] = scrub_text(
                "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
            )
        elif record.exc_text:
            # ``logging`` may have pre-formatted exc_text (cached); preserve it,
            # scrubbed — don't assume an upstream formatter already redacted.
            payload["traceback"] = scrub_text(record.exc_text)

        # Merge extras from ``logger.info("msg", extra={"k": "v"})``. These
        # keys appear as attributes on the record. Clashes with reserved keys
        # above are prefixed with ``extra_`` rather than silently dropped, so
        # callers see their data isn't lost.
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOGRECORD_ATTRS:
                continue
            if key.startswith("_"):
                continue
            target_key = key if key not in payload else f"extra_{key}"
            payload[target_key] = value

        # ``default=str`` is the "logging must never raise" guard — if an
        # ``extra`` happens to be a model instance or other non-JSON type,
        # repr it rather than crashing the logger.
        return json.dumps(payload, separators=(",", ":"), default=str)


class ScrubbingPlainFormatter(logging.Formatter):
    """Human-readable (non-JSON) formatter, hardened against secret leaks.

    The stdlib :class:`logging.Formatter` appends the exception traceback via
    :meth:`formatException`, and that text is produced INSIDE ``format()`` —
    after the :class:`~api.logging_config.SecretScrubber` filter has already
    run. So on the plain path the traceback would otherwise reach stdout
    unredacted (same root cause as the JSON path — see F3). We override
    :meth:`formatException` to route the rendered traceback through the shared
    :func:`~api.logging_config.scrub_text` before it is appended (and cached
    on ``record.exc_text``).

    Wired in as the ``plain`` formatter's factory by ``build_log_config``.
    Non-exception records are formatted exactly like the stdlib formatter.
    """

    def formatException(self, ei) -> str:  # noqa: N802 - stdlib hook name
        return scrub_text(super().formatException(ei))
