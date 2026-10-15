"""Validate the model and tool references declared by agents."""

from __future__ import annotations

from collections.abc import Collection

from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.models.config import model_exists
from latest_ai_development.models.schema import ModelsConfiguration


def validate_agents_configuration(
    definitions: tuple[AgentDefinition, ...],
    models_configuration: ModelsConfiguration,
    tool_names: Collection[str],
) -> None:
    """Ensure every agent references configured models and tools."""
    errors: list[str] = []

    for definition in definitions:
        _validate_agent_models(definition, models_configuration, errors)
        _validate_agent_tools(definition, tool_names, errors)

    if errors:
        details = _format_errors(errors)
        raise ValueError(f"Agent configuration validation failed:\n{details}")


def _validate_agent_models(
    definition: AgentDefinition,
    models_configuration: ModelsConfiguration,
    errors: list[str],
) -> None:
    """Check that every configured model exists in models.yaml."""
    for model_index, model in enumerate(definition.model):
        if model_exists(
            models_configuration,
            model.provider,
            model.model_id,
        ):
            continue

        model_role = "primary" if model_index == 0 else f"fallback #{model_index}"
        errors.append(
            f"agent '{definition.name}' references an unknown "
            f"{model_role} model "
            f"'{model.provider}/{model.model_id}'"
        )


def _validate_agent_tools(
    definition: AgentDefinition,
    tool_names: Collection[str],
    errors: list[str],
) -> None:
    """Check that every configured tool exists in connector configuration."""
    for tool_name in definition.tools:
        if tool_name in tool_names:
            continue

        errors.append(f"agent '{definition.name}' references unknown tool '{tool_name}'")


def _format_errors(errors: list[str]) -> str:
    """Format validation errors as a readable bullet list."""
    lines: list[str] = []
    for error in errors:
        lines.append(f"- {error}")
    return "\n".join(lines)
