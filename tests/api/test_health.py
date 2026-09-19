from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from latest_ai_development.api.health import health, readiness


def test_health_returns_liveness_status() -> None:
    assert health() == {"status": "ok"}


def test_readiness_returns_container_summary() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                container=SimpleNamespace(
                    workflow_definition=SimpleNamespace(name="blog_generation_workflow"),
                    agent_registry=SimpleNamespace(count=lambda: 5),
                    model_registry=SimpleNamespace(count=lambda: 2),
                )
            )
        )
    )

    assert readiness(request) == {
        "status": "ready",
        "workflow": "blog_generation_workflow",
        "agents": 5,
        "models": 2,
    }


def test_readiness_returns_503_when_container_is_missing() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(HTTPException) as exc_info:
        readiness(request)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "error": "service_not_ready",
        "message": "Application container is not initialized",
    }
