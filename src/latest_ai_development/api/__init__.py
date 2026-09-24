"""Combine all API route files into one router."""

from fastapi import APIRouter

from latest_ai_development.api.health import router as health_router
from latest_ai_development.api.workflow import build_workflow_router
from latest_ai_development.context.runtime import ContextRuntime
from latest_ai_development.stages.schema import WorkflowDefinition


def build_api_router(
    definition: WorkflowDefinition,
    context_configuration: ContextRuntime | None = None,
) -> APIRouter:
    """Combine health and the endpoint generated for the configured workflow."""
    router = APIRouter()
    router.include_router(health_router)
    router.include_router(build_workflow_router(definition, context_configuration))
    return router


__all__ = ["build_api_router"]
