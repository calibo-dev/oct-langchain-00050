from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from latest_ai_development.config.settings import get_settings
from latest_ai_development.config.validators import validate_configuration
from latest_ai_development.logging_utils import configure_logging
from latest_ai_development.tracing import initialize_langsmith_tracing
from latest_ai_development.workflow import LatestAiDevelopmentWorkflow

# Load settings
settings = get_settings()
configure_logging(getattr(settings, "log_level", "INFO"))
logger = logging.getLogger(__name__)

# Validate configuration at startup
try:
    validate_configuration()
except Exception:
    logger.exception("Startup configuration validation failed")
    raise

# Initialize workflow controller
try:
    workflow = LatestAiDevelopmentWorkflow()
except Exception:
    logger.exception("Workflow initialization failed")
    raise

API_ROOT_PATH = settings.normalized_api_root_path


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_langsmith_tracing()
    yield


# Initialize FastAPI application
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="LangChain workflow for automated research and report generation",
    root_path=API_ROOT_PATH,
    lifespan=lifespan,
)


class AskRequest(BaseModel):
    topic: str


@app.get("/health")
def health() -> dict[str, str]:
    """
    Health check endpoint.
    """
    return {"status": "ok"}


@app.post("/ask")
def ask(request: AskRequest):
    """
    Execute the research + reporting workflow.
    """
    flow_run_id = uuid4().hex[:12]

    logger.info(
        "Request started | flow_run_id=%s | topic=%s",
        flow_run_id,
        request.topic,
    )

    inputs = {
        "topic": request.topic,
        "current_year": datetime.now().year,
        "knowledge_context": "",
    }

    try:
        try:
            result = workflow.kickoff(inputs, flow_run_id=flow_run_id)
        except TypeError as exc:
            if "unexpected keyword argument 'flow_run_id'" not in str(exc):
                raise
            result = workflow.kickoff(inputs)
    except Exception as exc:
        logger.error(f"Error occurred while asking the workflow: {exc}")
        content = {
            "status": "error",
            "response": "Something went wrong. Please contact your administrator.",
        }
        return JSONResponse(status_code=500, content=content)

    logger.info(
        "Request completed | flow_run_id=%s | topic=%s",
        flow_run_id,
        request.topic,
    )

    return {
        "status": "success",
        "response": {
            "topic": result.get("topic"),
            "report": result.get("report"),
        },
    }


if API_ROOT_PATH:
    app.add_api_route(
        f"{API_ROOT_PATH}/health",
        health,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        f"{API_ROOT_PATH}/ask",
        ask,
        methods=["POST"],
        include_in_schema=False,
    )


# CLI-compatible entrypoint
def run() -> None:
    import uvicorn

    uvicorn.run(
        "latest_ai_development.main:app",
        host=settings.api_host,
        port=settings.port,
        reload=settings.debug,
        log_level=str(getattr(settings, "log_level", "INFO")).lower(),
    )


if __name__ == "__main__":
    run()
