"""Create and configure the FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from latest_ai_development.api import build_api_router
from latest_ai_development.api.error_handlers import register_error_handlers
from latest_ai_development.api.middleware import RequestLoggingMiddleware
from latest_ai_development.core.container import get_application_container

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan hook.

    The application container is created before the FastAPI app is returned, so
    there is no extra startup work here. Connector resources opened lazily while
    serving requests are closed during shutdown.
    """
    try:
        yield
    finally:
        # Connector resources are opened lazily and shared by configured tools.
        # Closing them here keeps shutdown deterministic in servers and tests.
        app.state.container.connection_registry.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    try:
        container = get_application_container()
    except Exception:
        logger.exception("Application container initialization failed")
        raise

    settings = container.settings
    api_root_path = settings.api_root_path
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="LangChain workflow for configuration-driven content generation",
        root_path=api_root_path,
        lifespan=lifespan,
    )
    app.add_middleware(RequestLoggingMiddleware)
    register_error_handlers(app)

    # Store startup-created objects on app.state so API routes can reuse them.
    app.state.container = container
    app.state.settings = settings
    app.state.workflow = container.workflow

    api_router = build_api_router(
        container.workflow_definition, container.workflow.context_configuration
    )
    app.include_router(api_router)
    if api_root_path:
        app.include_router(api_router, prefix=api_root_path, include_in_schema=False)

    return app


__all__ = ["create_app", "lifespan"]
