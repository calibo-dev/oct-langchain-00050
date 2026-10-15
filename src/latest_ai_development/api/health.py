"""Liveness and readiness endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from latest_ai_development.api.responses import build_error_payload

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Return liveness status.

    This endpoint should stay lightweight. It only means the process is alive.
    """
    return {"status": "ok"}


@router.get("/ready")
def readiness(request: Request) -> dict[str, Any]:
    """Return readiness status.

    Readiness means the application container exists and the workflow runtime is
    ready to serve requests.
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=build_error_payload(
                error="service_not_ready",
                message="Application container is not initialized",
            ),
        )

    return {
        "status": "ready",
        "workflow": container.workflow_definition.name,
        "agents": container.agent_registry.count(),
        "models": container.model_registry.count(),
    }
