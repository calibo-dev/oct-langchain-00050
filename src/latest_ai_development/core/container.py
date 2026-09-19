"""Application container and cached container access."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from latest_ai_development.agents.registry import AgentRegistry
from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.connections.registry import ConnectionRegistry
from latest_ai_development.core.settings import Settings
from latest_ai_development.models.registry import ModelRegistry
from latest_ai_development.stages.schema import WorkflowDefinition
from latest_ai_development.tools.registry import ToolRegistry
from latest_ai_development.workflow import LatestAiDevelopmentWorkflow


@dataclass(frozen=True)
class ApplicationContainer:
    """Objects created once at startup and shared by all requests."""

    settings: Settings
    connection_registry: ConnectionRegistry
    model_registry: ModelRegistry
    tool_registry: ToolRegistry
    agent_definitions: tuple[AgentDefinition, ...]
    agent_registry: AgentRegistry
    workflow_definition: WorkflowDefinition
    workflow: LatestAiDevelopmentWorkflow


@lru_cache
def get_application_container() -> ApplicationContainer:
    """Return the startup container.

    ``lru_cache`` makes this function run the builder only once per Python
    process. Every API request then reuses the same workflow, agents, and models.
    """
    from latest_ai_development.core.container_builder import ApplicationContainerBuilder

    return ApplicationContainerBuilder().build()


__all__ = ["ApplicationContainer", "get_application_container"]
