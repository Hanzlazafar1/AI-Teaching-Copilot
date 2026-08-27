"""Phase 11.1 — per-request correlation ID plumbing.

A single UUID is assigned per inbound HTTP request and threaded through three
channels:

  1. ``ContextVar`` so any code (validator, retrieval helper, OpenAI client
     wrapper) can read the current request's id without it being passed as a
     function argument.
  2. Python logging — the :class:`RequestIdFilter` stamps every ``LogRecord``
     with ``req_id`` so structured logs are correlatable.
  3. The ``X-Request-ID`` response header, so client tooling (curl, the LMS,
     on-call dashboards) can surface it to the user for bug reports.

The middleware also honors an inbound ``X-Request-ID`` header when the caller
supplies one — useful for tracing across an LMS → copilot hop. The incoming
value is validated as a UUID; anything else is discarded and we mint our own,
so a malicious client can't inject arbitrary log text.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Optional

from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Empty string sentinel (not None) so %-formatting in the log format string
# renders as "" instead of "None" for out-of-request log lines.
_EMPTY = ""
_request_id_var: ContextVar[str] = ContextVar("req_id", default=_EMPTY)


REQUEST_ID_HEADER = "X-Request-ID"


def get_request_id() -> str:
    """Return the current request's id, or an empty string outside a request."""
    return _request_id_var.get()


def set_request_id(value: str) -> object:
    """Set the request id for the current context. Returns a token the caller
    must pass back to :func:`reset_request_id` to restore the prior value
    (follows the ``ContextVar`` contract).
    """
    return _request_id_var.set(value)


def reset_request_id(token: object) -> None:
    _request_id_var.reset(token)  # type: ignore[arg-type]


# RFC 4122 UUID shape: 8-4-4-4-12 hex digits. We accept any case and do not
# require a specific version so both v4 (our mint) and v7 (other services)
# work. Reject anything else (length, hyphen count, non-hex chars) so a
# spoofed header can't inject log poisoning.
_UUID_SHAPE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _coerce_request_id(raw: Optional[str]) -> str:
    """Accept an inbound X-Request-ID iff it parses as a UUID; else mint one."""
    if raw and _UUID_SHAPE.match(raw):
        return raw
    return str(uuid.uuid4())


class RequestIdFilter(logging.Filter):
    """Stamps every LogRecord with the current ``req_id``.

    Install once on the root logger (see ``main.py``). The filter is process-
    wide — log records emitted from background tasks that do not run inside
    a request will carry ``req_id=""``, which is intentional.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - std name
        # Always overwrite; a handler might be reused across requests.
        record.req_id = get_request_id()
        return True


class RequestIdMiddleware:
    """Pure-ASGI middleware that assigns and exposes the per-request id.

    Written as raw ASGI (not ``BaseHTTPMiddleware``) deliberately:
    ``BaseHTTPMiddleware`` wraps ``call_next`` in a threadsafe adapter that
    swallows/reshapes downstream exceptions, preventing the ASGI
    ``ExceptionMiddleware`` above it from seeing them — so registered
    ``Exception`` handlers never run. ``BaseHTTPMiddleware`` has this issue
    upstream; pure ASGI sidesteps it entirely.

    Responsibilities:
      1. Read (and validate) an inbound ``X-Request-ID`` header, or mint one.
      2. Set the ``ContextVar`` for the duration of the request.
      3. Inject ``X-Request-ID`` on the outgoing response by intercepting the
         ``http.response.start`` ASGI message.
      4. Reset the ContextVar in ``finally`` so values don't leak across
         requests sharing a thread.

    Must be the outermost middleware (``add_middleware`` last) so the id is
    set before any downstream handler runs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Parse inbound header from raw scope headers (list of [bytes, bytes]).
        inbound: Optional[str] = None
        for name, value in scope.get("headers") or []:
            if name.decode("latin-1").lower() == REQUEST_ID_HEADER.lower():
                inbound = value.decode("latin-1")
                break
        req_id = _coerce_request_id(inbound)
        req_id_bytes = req_id.encode("latin-1")

        # Stash on scope.state so exception handlers can recover the id even
        # when they run ABOVE this middleware (Starlette's ServerErrorMiddleware
        # is outermost, so by the time it invokes a generic Exception handler
        # the ContextVar may already have been reset). ``scope["state"]`` is
        # Starlette's standard per-request dict — survives the entire
        # request regardless of middleware ordering.
        scope.setdefault("state", {})
        scope["state"]["req_id"] = req_id

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                # Replace any stale value a downstream handler may have set.
                headers = [
                    (n, v) for (n, v) in headers
                    if n.decode("latin-1").lower() != REQUEST_ID_HEADER.lower()
                ]
                headers.append(
                    (REQUEST_ID_HEADER.encode("latin-1"), req_id_bytes)
                )
                message = {**message, "headers": headers}
            await send(message)

        token = set_request_id(req_id)
        try:
            await self.app(scope, receive, send_with_header)
        finally:
            reset_request_id(token)


def req_id_from_request(request: "object") -> str:
    """Read the request id from a Starlette ``Request`` (or any object with
    ``.state``). Prefers ``state.req_id`` (survives middleware teardown),
    falls back to the ContextVar. Returns ``""`` if unset.
    """
    state_id = getattr(getattr(request, "state", None), "req_id", None)
    if state_id:
        return state_id
    return get_request_id()
