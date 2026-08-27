"""Phase 11.1 — structured application errors.

Every user-visible error in the API gets a stable ``error_code`` so clients can
branch on it, an HTTP status code that correctly reflects whether the failure
is retry-worthy (5xx) or terminal (4xx), and a ``req_id`` stamp tying it to
server logs.

Usage pattern:

    from api.errors import AppError, ErrorCode

    if _check_rate_limit(user_id):
        raise AppError.rate_limited(retry_after=60)

The global exception handler in ``main.py`` converts ``AppError`` instances to
the wire ``ErrorResponse`` envelope below. Unhandled ``Exception`` subclasses
are mapped to ``INTERNAL`` with HTTP 500 (full traceback logged, not sent to
the client).

This module deliberately holds no business logic — it is pure plumbing so it
can be imported from anywhere (including ``config.py``) without cycles.
"""

from __future__ import annotations

import enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorCode(str, enum.Enum):
    """Stable error-code vocabulary. Add entries here, not elsewhere.

    Keep values lowercase_with_underscores so JSON consumers don't have to
    guess the casing. String subclass so the enum is JSON-serializable without
    a custom encoder.
    """

    # 4xx — terminal for the client
    VALIDATION_ERROR = "validation_error"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"

    # 5xx — transient or server-side; client may retry
    UPSTREAM_FAILED = "upstream_failed"
    TIMED_OUT = "timed_out"
    INTERNAL = "internal"


class ErrorResponse(BaseModel):
    """Wire envelope for all error responses. Stamped with ``req_id`` by the
    exception handler so a user-reported failure can be correlated to logs.
    """

    error_code: ErrorCode
    message: str
    req_id: Optional[str] = Field(
        default=None,
        description="Correlation id stamped at request entry.",
    )
    details: Optional[dict[str, Any]] = None


class AppError(Exception):
    """Domain exception carrying enough context for a well-formed response.

    Raise this from route handlers (or anywhere below them) to produce a
    differentiated error response. The exception carries the HTTP status
    explicitly — it is not inferred from ``error_code`` — because several
    codes (e.g. ``UPSTREAM_FAILED``) could map to either 502 or 503 depending
    on context.
    """

    def __init__(
        self,
        error_code: ErrorCode,
        http_status: int,
        message: str,
        *,
        details: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status
        self.message = message
        self.details = details
        self.headers = headers or {}

    # --- Factory helpers -----------------------------------------------------
    # Factories exist so call-sites read declaratively
    # (``raise AppError.rate_limited(...)``) rather than re-specifying status
    # codes inline, which drifts over time.

    @classmethod
    def rate_limited(
        cls,
        *,
        retry_after: Optional[int] = None,
        message: str = "Rate limit exceeded. Please try again later.",
    ) -> "AppError":
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        return cls(
            ErrorCode.RATE_LIMITED, 429, message,
            details={"retry_after": retry_after} if retry_after else None,
            headers=headers,
        )

    @classmethod
    def validation_error(cls, message: str, **details: Any) -> "AppError":
        return cls(ErrorCode.VALIDATION_ERROR, 400, message, details=details or None)

    @classmethod
    def unauthorized(cls, message: str = "Authentication required.") -> "AppError":
        return cls(ErrorCode.UNAUTHORIZED, 401, message)

    @classmethod
    def forbidden(cls, message: str = "Not authorized.") -> "AppError":
        return cls(ErrorCode.FORBIDDEN, 403, message)

    @classmethod
    def not_found(cls, message: str = "Resource not found.") -> "AppError":
        return cls(ErrorCode.NOT_FOUND, 404, message)

    @classmethod
    def budget_exhausted(
        cls,
        *,
        scope: str,
        message: str = "Budget exhausted for this period.",
    ) -> "AppError":
        return cls(
            ErrorCode.BUDGET_EXHAUSTED, 429, message,
            details={"scope": scope},
        )

    @classmethod
    def upstream_failed(
        cls,
        *,
        upstream: str,
        message: Optional[str] = None,
    ) -> "AppError":
        msg = message or f"{upstream} request failed. Please retry."
        return cls(
            ErrorCode.UPSTREAM_FAILED, 503, msg,
            details={"upstream": upstream},
        )

    @classmethod
    def timed_out(cls, message: str = "Request timed out.") -> "AppError":
        return cls(ErrorCode.TIMED_OUT, 504, message)

    @classmethod
    def internal(cls, message: str = "Internal server error.") -> "AppError":
        return cls(ErrorCode.INTERNAL, 500, message)

    # --- Serialization -------------------------------------------------------

    def to_response(self, *, req_id: Optional[str] = None) -> ErrorResponse:
        return ErrorResponse(
            error_code=self.error_code,
            message=self.message,
            req_id=req_id,
            details=self.details,
        )
