"""Application-wide structured error handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from latest_ai_development.api.responses import error_response

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """Register consistent JSON error responses for all API failures."""

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        _: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        """Return a clean JSON response for FastAPI HTTPException errors."""
        return _http_error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Return readable validation errors for invalid request bodies."""
        return error_response(
            status_code=422,
            error="request_validation_failed",
            message="Request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Hide unexpected exception details from API clients and log them."""
        logger.exception(
            "Unhandled API error | method=%s | path=%s",
            request.method,
            request.url.path,
        )
        return error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error="internal_server_error",
            message="Unexpected server error",
        )


def _http_error_response(exc: HTTPException) -> JSONResponse:
    """Convert HTTPException into the standard error shape."""
    if isinstance(exc.detail, dict):
        payload = _normalize_error_payload(exc.detail)
        return JSONResponse(status_code=exc.status_code, content=payload)

    return error_response(
        status_code=exc.status_code,
        error="http_error",
        message=str(exc.detail),
    )


def _normalize_error_payload(detail: dict[str, Any]) -> dict[str, Any]:
    """Keep custom HTTPException details while ensuring required keys exist."""
    payload = dict(detail)

    if "error" not in payload:
        payload["error"] = "http_error"
    if "message" not in payload:
        payload["message"] = "Request failed"

    return payload
