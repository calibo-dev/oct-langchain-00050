"""Build a workflow endpoint and its string payload from YAML configuration."""

import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ConfigDict, StringConstraints, create_model

from latest_ai_development.api.responses import build_error_payload
from latest_ai_development.stages.schema import WorkflowDefinition
from latest_ai_development.workflow import WorkflowExecutionError

logger = logging.getLogger(__name__)


def build_workflow_router(definition: WorkflowDefinition) -> APIRouter:
    """Generate the request schema once, before FastAPI registers the route."""
    input_type = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
    fields = {}
    for input_name in definition.inputs:
        fields[input_name] = (input_type, ...)

    payload_model = create_model(
        f"{definition.name}_request",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )

    # Use the actual generated class in the annotation so FastAPI can validate
    # the body and document every configured field in OpenAPI.
    def endpoint(payload: payload_model, request: Request) -> dict[str, str]:
        return run_workflow(payload.model_dump(), request)

    router = APIRouter()
    router.add_api_route(
        f"/{definition.name}",
        endpoint,
        methods=["POST"],
        name=definition.name,
        summary=f"Run {definition.name}",
    )
    return router


def run_workflow(inputs: dict[str, str], request: Request) -> dict[str, str]:
    """Run the configured workflow."""
    flow_run_id = uuid4().hex[:12]

    logger.info(
        "Request started | flow_run_id=%s",
        flow_run_id,
    )

    workflow = request.app.state.workflow
    try:
        result = workflow.kickoff(inputs, flow_run_id=flow_run_id)
    except WorkflowExecutionError as exc:
        logger.exception(
            "Workflow failed | flow_run_id=%s",
            flow_run_id,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=build_error_payload(
                error="workflow_execution_failed",
                message="Workflow execution failed",
                details={
                    "flow_run_id": flow_run_id,
                    "reason": str(exc),
                },
            ),
        ) from exc
    except Exception as exc:
        logger.exception(
            "Request failed | flow_run_id=%s",
            flow_run_id,
        )
        raise HTTPException(
            status_code=500,
            detail=build_error_payload(
                error="workflow_execution_failed",
                message="Workflow execution failed",
                details={"flow_run_id": flow_run_id},
            ),
        ) from exc

    logger.info(
        "Request completed | flow_run_id=%s",
        flow_run_id,
    )

    return result
