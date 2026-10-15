"""Construct runtime LangChain agents from validated definitions."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware

from latest_ai_development.agents.registry import AgentRegistry
from latest_ai_development.agents.runtime import (
    AgentRuntime,
    StrictToolCallingMiddleware,
    ToolFailureMiddleware,
)
from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.context.middleware import ContextPromptMiddleware
from latest_ai_development.context.runtime import CONTEXT_REFERENCE, ContextRuntime
from latest_ai_development.models.registry import ModelRegistry

logger = logging.getLogger(__name__)


def build_agent_registry(
    definitions: tuple[AgentDefinition, ...],
    model_registry: ModelRegistry,
    tool_registry: Mapping[str, Any],
    context_configuration: ContextRuntime | None = None,
) -> AgentRegistry:
    """Create every configured primary/fallback agent and return one registry."""
    agents: dict[str, AgentRuntime] = {}

    for definition in definitions:
        try:
            runtime = _create_agent_runtime(
                model_registry, tool_registry, definition, context_configuration
            )
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
    tool_registry: Mapping[str, Any],
    definition: AgentDefinition,
    context_configuration: ContextRuntime | None = None,
) -> AgentRuntime:
    """Create primary and fallback LangChain agent objects during startup."""
    runtime_agents: list[Any] = []
    model_names: list[str] = []
    tools = tuple(tool_registry[name] for name in definition.tools)
    context_options: dict[str, Any] = {}
    if context_configuration is not None:
        context_configuration.validate_prompt(definition.system_prompt)
        context_options["context_schema"] = context_configuration.schema
    for model in definition.model:
        llm = model_registry.get(model.provider, model.model_id)
        # Strict tool conversion is OpenAI-specific; other providers receive
        # their native schemas without an unsupported model parameter.
        middleware: list[AgentMiddleware] = [ToolFailureMiddleware()] if tools else []
        if context_configuration is not None and CONTEXT_REFERENCE.search(definition.system_prompt):
            middleware.append(ContextPromptMiddleware(definition.system_prompt))
        if tools and model.provider.strip().lower() == "openai":
            middleware.append(StrictToolCallingMiddleware())
        runtime_agents.append(
            create_agent(
                model=llm,
                tools=tools,
                middleware=middleware,
                system_prompt=definition.system_prompt,
                name=definition.name,
                **context_options,
            )
        )
        model_names.append(f"{model.provider}/{model.model_id}")

    return AgentRuntime(
        name=definition.name,
        agents=tuple(runtime_agents),
        model_names=tuple(model_names),
    )


__all__ = ["build_agent_registry"]
