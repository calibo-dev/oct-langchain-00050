"""API middleware used by the FastAPI application."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log each API request with method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Log before and after FastAPI handles one request."""
        started_at = perf_counter()
        method = request.method
        path = request.url.path

        logger.info("API request started | method=%s | path=%s", method, path)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "API request failed | method=%s | path=%s | elapsed=%.3fs",
                method,
                path,
                perf_counter() - started_at,
            )
            raise

        logger.info(
            "API request completed | method=%s | path=%s | status_code=%s | elapsed=%.3fs",
            method,
            path,
            response.status_code,
            perf_counter() - started_at,
        )
        return response
