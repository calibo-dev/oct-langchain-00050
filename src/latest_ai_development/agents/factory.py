"""Construct runtime LangChain agents from validated definitions."""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents import create_agent

from latest_ai_development.agents.registry import AgentRegistry
from latest_ai_development.agents.runtime import (
    AgentRuntime,
    StrictToolCallingMiddleware,
)
from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.models.registry import ModelRegistry
from latest_ai_development.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def build_agent_registry(
    definitions: tuple[AgentDefinition, ...],
    model_registry: ModelRegistry,
    tool_registry: ToolRegistry,
) -> AgentRegistry:
    """Create every configured primary/fallback agent and return one registry."""
    agents: dict[str, AgentRuntime] = {}

    for definition in definitions:
        try:
            runtime = _create_agent_runtime(model_registry, tool_registry, definition)
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            primary_model = definition.primary_model
            logger.error(
                "Agent registration failed agent=%s provider=%s model_id=%s reason=%s",
                definition.name,
                primary_model.provider,
                primary_model.model_id,
                reason,
            )
            raise RuntimeError(
                f"Unable to register agent '{definition.name}' with "
                f"'{primary_model.provider}/{primary_model.model_id}': {reason}"
            ) from exc

        agents[definition.name] = runtime
        logger.info("Agent created agent=%s", definition.name)

    return AgentRegistry(agents)


def _create_agent_runtime(
    model_registry: ModelRegistry,
    tool_registry: ToolRegistry,
    definition: AgentDefinition,
) -> AgentRuntime:
    """Create primary and fallback LangChain agent objects during startup."""
    runtime_agents: list[Any] = []
    model_names: list[str] = []
    tools = tool_registry.get(definition.tools)
    middleware = [StrictToolCallingMiddleware()] if tools else []

    for model in definition.model:
        llm = model_registry.get(model.provider, model.model_id)
        runtime_agents.append(
            create_agent(
                model=llm,
                tools=tools,
                middleware=middleware,
                system_prompt=definition.system_prompt,
                name=definition.name,
            )
        )
        model_names.append(f"{model.provider}/{model.model_id}")

    return AgentRuntime(
        name=definition.name,
        agents=tuple(runtime_agents),
        model_names=tuple(model_names),
    )


__all__ = ["build_agent_registry"]
