"""Small helpers for consistent LangSmith trace names, tags, and metadata."""

from __future__ import annotations

from typing import Any

from latest_ai_development.stages.schema import StageDefinition


def build_workflow_trace_extra(workflow_name: str, flow_run_id: str) -> dict[str, Any]:
    """Build LangSmith metadata for the parent workflow run."""
    return {
        "name": f"workflow:{workflow_name}",
        "metadata": {
            "flow_run_id": flow_run_id,
            "workflow": workflow_name,
        },
        "tags": [
            "workflow",
            workflow_name,
            f"flow_run_id:{flow_run_id}",
        ],
    }


def build_stage_trace_extra(
    workflow_name: str,
    stage: StageDefinition,
    flow_run_id: str,
) -> dict[str, Any]:
    """Build LangSmith metadata for one stage child run."""
    return {
        "name": f"stage:{stage.name}",
        "metadata": {
            "flow_run_id": flow_run_id,
            "workflow": workflow_name,
            "stage": stage.name,
            "stage_execution": stage.execution,
        },
        "tags": [
            "stage",
            workflow_name,
            stage.name,
            f"flow_run_id:{flow_run_id}",
        ],
    }


def build_agent_trace_extra(
    workflow_name: str,
    stage_name: str,
    agent_name: str,
    flow_run_id: str,
) -> dict[str, Any]:
    """Build LangSmith metadata for one agent child run."""
    return {
        "name": f"agent:{agent_name}",
        "metadata": _base_agent_metadata(
            workflow_name,
            stage_name,
            agent_name,
            flow_run_id,
        ),
        "tags": [
            "agent",
            workflow_name,
            stage_name,
            agent_name,
            f"flow_run_id:{flow_run_id}",
        ],
    }


def build_agent_invoke_config(
    workflow_name: str,
    stage_name: str,
    agent_name: str,
    flow_run_id: str,
) -> dict[str, Any]:
    """Build the LangChain config passed into agent.invoke()."""
    return {
        "run_name": f"langchain-agent:{agent_name}",
        "metadata": _base_agent_metadata(
            workflow_name,
            stage_name,
            agent_name,
            flow_run_id,
        ),
        "tags": [
            "langchain-agent",
            workflow_name,
            stage_name,
            agent_name,
            f"flow_run_id:{flow_run_id}",
        ],
    }


def _base_agent_metadata(
    workflow_name: str,
    stage_name: str,
    agent_name: str,
    flow_run_id: str,
) -> dict[str, str]:
    """Return metadata shared by traceable agent runs and LangChain runs."""
    return {
        "flow_run_id": flow_run_id,
        "workflow": workflow_name,
        "stage": stage_name,
        "agent": agent_name,
    }
