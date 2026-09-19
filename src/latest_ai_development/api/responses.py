"""Shared API response helpers."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def build_error_payload(
    error: str,
    message: str,
    details: Any | None = None,
) -> dict[str, Any]:
    """Build a consistent error response body."""
    payload: dict[str, Any] = {
        "error": error,
        "message": message,
    }
    if details is not None:
        payload["details"] = details
    return payload


def error_response(
    status_code: int,
    error: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    """Return a FastAPI JSON response with the standard error shape."""
    return JSONResponse(
        status_code=status_code,
        content=build_error_payload(
            error=error,
            message=message,
            details=details,
        ),
    )
