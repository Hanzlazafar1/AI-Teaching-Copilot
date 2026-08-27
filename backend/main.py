"""Brady AI Writing Co-Pilot v4 — FastAPI application.

Custom RAG pipeline with hybrid search, adaptive query understanding,
and time-aware quality gate.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import asyncio

import httpx
import openai
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.errors import AppError, ErrorCode, ErrorResponse
from api.health import run_readiness_probes
from api.logging_config import configure_logging
from api.request_context import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    req_id_from_request,
)
from api.routes_v4 import router
from config import settings
from generation.prompts import init_prompts

# ---------------------------------------------------------------------------
# Logging — centralised via api.logging_config (Phase 11.7).
#
# configure_logging() owns every logger used by this process:
#   - our app modules
#   - uvicorn's three internal loggers (uvicorn, uvicorn.error, uvicorn.access)
#   - noisy third-party (httpx / openai / urllib3 → WARNING)
#
# Filters installed on the single stdout handler:
#   - RequestIdFilter      — stamps req_id from the per-request ContextVar
#   - StaticFieldsFilter   — stamps service + env (from settings)
#   - SecretScrubber       — redacts OpenAI keys / bearer / JWT shapes before
#                            records reach any formatter
#
# Formatter is selected by LOG_FORMAT:
#   - "plain" (default, human-readable for local dev)
#   - "json"  (one line per record, for production container logs)
# ---------------------------------------------------------------------------

configure_logging(settings)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize prompts and framework rules at startup."""
    # Re-run logging config here so we reclaim uvicorn's loggers AFTER
    # uvicorn's own bootstrap dictConfig has run (which happens between
    # our import-time call and the lifespan start). dictConfig is
    # idempotent, so the double-call is safe.
    configure_logging(settings)
    init_prompts()
    logger.info("Brady AI Writing Co-Pilot v4 started")
    yield
    logger.info("Brady AI Writing Co-Pilot v4 shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Brady AI Writing Co-Pilot v4",
    version="4.0.0",
    description="Custom RAG pipeline for K-12 writing instruction using Smekens methodology.",
    lifespan=lifespan,
)

# Middleware is onion-shaped: last-added is outermost. RequestIdMiddleware must
# be outermost so `req_id` is set before CORS or the route handler run.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)
app.add_middleware(RequestIdMiddleware)

app.include_router(router)


# ---------------------------------------------------------------------------
# Exception handlers — convert raised errors into the structured envelope.
# ---------------------------------------------------------------------------


def _error_json(app_error: AppError, request: Request) -> JSONResponse:
    """Build a JSONResponse from an AppError, stamping the request's id + any
    headers the error carries (e.g. ``Retry-After``)."""
    req_id = req_id_from_request(request) or None
    body = app_error.to_response(req_id=req_id)
    return JSONResponse(
        status_code=app_error.http_status,
        content=body.model_dump(mode="json"),
        headers=app_error.headers or None,
    )


@app.exception_handler(AppError)
async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning(
        "AppError %s (%d): %s",
        exc.error_code.value,
        exc.http_status,
        exc.message,
    )
    return _error_json(exc, request)


@app.exception_handler(RequestValidationError)
async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    err = AppError.validation_error("Request validation failed", errors=exc.errors())
    logger.warning("Validation failure on %s: %s", request.url.path, exc.errors())
    return _error_json(err, request)


@app.exception_handler(openai.APITimeoutError)
async def _openai_timeout_handler(
    request: Request, exc: openai.APITimeoutError
) -> JSONResponse:
    """OpenAI side timed out → 504. Retry-worthy for the client."""
    logger.warning("OpenAI timeout on %s: %s", request.url.path, exc)
    return _error_json(
        AppError.timed_out(message="Upstream LLM call timed out. Please retry."),
        request,
    )


@app.exception_handler(openai.AuthenticationError)
async def _openai_auth_handler(
    request: Request, exc: openai.AuthenticationError
) -> JSONResponse:
    """OpenAI rejected our API key → server-side config bug, 500 not 503.

    This is NOT retry-worthy from the client's perspective — their retry
    would just fail the same way. Mapping to INTERNAL signals "operator fix
    needed, don't retry." The underlying error is logged at ERROR so it
    pages the on-call rather than hiding in WARN-level noise.
    """
    logger.error("OpenAI rejected our API key on %s — config issue", request.url.path)
    return _error_json(AppError.internal(), request)


@app.exception_handler(openai.APIError)
async def _openai_api_handler(
    request: Request, exc: openai.APIError
) -> JSONResponse:
    """Catch-all for OpenAI SDK errors (connection, status 5xx, rate limit
    from OpenAI, etc.) → 503 UPSTREAM_FAILED. Retry-worthy for the client."""
    logger.warning(
        "OpenAI upstream error on %s: %s: %s",
        request.url.path, type(exc).__name__, exc,
    )
    return _error_json(AppError.upstream_failed(upstream="openai"), request)


@app.exception_handler(httpx.TimeoutException)
async def _httpx_timeout_handler(
    request: Request, exc: httpx.TimeoutException
) -> JSONResponse:
    """Raw httpx timeout (e.g., from embedding calls that bypass the openai
    SDK's own timeout translation) → 504."""
    logger.warning("httpx timeout on %s: %s", request.url.path, exc)
    return _error_json(
        AppError.timed_out(message="Upstream request timed out. Please retry."),
        request,
    )


@app.exception_handler(httpx.HTTPError)
async def _httpx_error_handler(
    request: Request, exc: httpx.HTTPError
) -> JSONResponse:
    """Any other httpx-level failure (connection refused, DNS, TLS) → 503."""
    logger.warning(
        "httpx upstream error on %s: %s: %s",
        request.url.path, type(exc).__name__, exc,
    )
    return _error_json(AppError.upstream_failed(upstream="httpx"), request)


@app.exception_handler(asyncio.TimeoutError)
async def _asyncio_timeout_handler(
    request: Request, exc: asyncio.TimeoutError
) -> JSONResponse:
    """Route-level asyncio timeout (e.g., ``asyncio.wait_for`` tripping) → 504."""
    logger.warning("asyncio timeout on %s", request.url.path)
    return _error_json(AppError.timed_out(), request)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    # Full traceback to logs; sanitized envelope to the client. NEVER leak the
    # exception message to the response — it may contain secrets (stack frames,
    # env values, DB rows).
    logger.exception("Unhandled exception on %s", request.url.path)
    return _error_json(AppError.internal(), request)


# ---------------------------------------------------------------------------
# Health (Phase 11.6)
#
# Two endpoints with different operational meaning:
#
#   /health/live  — process liveness. Always OK unless the worker is wedged.
#                    Use as K8s livenessProbe (failure => restart pod).
#   /health/ready — request readiness. Probes Qdrant + library index + OpenAI
#                    (cached 30s). Use as K8s readinessProbe and for load-
#                    balancer health checks (failure => stop sending traffic,
#                    but DON'T restart — dependency outage, restarts won't help).
#
# The legacy /health is kept as an alias of /health/live so existing tooling
# (including tests/acceptance/conftest.py) continues to work.
# ---------------------------------------------------------------------------


def _live_payload() -> dict:
    return {"status": "ok", "version": "4.0.0"}


@app.get("/health")
async def health_legacy():
    # Alias of /health/live for backwards compatibility.
    return _live_payload()


@app.get("/health/live")
async def health_live():
    return _live_payload()


@app.get("/health/ready")
async def health_ready():
    overall_ok, probes = await run_readiness_probes()
    body = {
        "status": "ok" if overall_ok else "degraded",
        "version": "4.0.0",
        "probes": [p.to_dict() for p in probes],
    }
    if overall_ok:
        return body
    # 503 so K8s / load balancers take us out of rotation. The per-probe
    # payload lets on-call see WHICH subsystem is unhealthy without
    # needing log access.
    return JSONResponse(status_code=503, content=body)
