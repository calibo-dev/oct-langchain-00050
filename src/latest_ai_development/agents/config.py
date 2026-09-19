"""Load and select agent configuration from agents.yaml."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from latest_ai_development.agents.schema import (
    AgentDefinition,
    AgentModel,
    AgentsConfiguration,
)
from latest_ai_development.core.settings import CONFIG_DIR, load_yaml_file


def load_agent_definitions(
    required_agent_names: Iterable[str] | None = None,
) -> tuple[AgentDefinition, ...]:
    """Load all agents or only the agents used by the active workflow."""
    raw_configuration = load_yaml_file(CONFIG_DIR / "agents.yaml")
    if required_agent_names is not None:
        raw_configuration = _select_required_agents(
            raw_configuration,
            required_agent_names,
        )

    try:
        configuration = AgentsConfiguration.model_validate(raw_configuration)
    except ValidationError as exc:
        raise ValueError(f"Invalid agents.yaml configuration:\n{exc}") from exc

    return tuple(configuration.agents)


def collect_workflow_agent_names(
    agent_names_by_stage: Iterable[Iterable[str]],
) -> tuple[str, ...]:
    """Return unique agent names in workflow order."""
    ordered_names: list[str] = []
    seen_names: set[str] = set()

    for stage_agent_names in agent_names_by_stage:
        for agent_name in stage_agent_names:
            if agent_name in seen_names:
                continue
            ordered_names.append(agent_name)
            seen_names.add(agent_name)

    return tuple(ordered_names)


def collect_agent_model_references(
    definitions: Iterable[AgentDefinition],
) -> tuple[AgentModel, ...]:
    """Return unique primary and fallback models used by active agents."""
    ordered_models: list[AgentModel] = []
    seen_model_keys: set[tuple[str, str]] = set()

    for definition in definitions:
        for model in definition.model:
            model_key = (model.provider.strip().lower(), model.model_id.strip())
            if model_key in seen_model_keys:
                continue
            ordered_models.append(model)
            seen_model_keys.add(model_key)

    return tuple(ordered_models)


def collect_agent_tool_references(
    definitions: Iterable[AgentDefinition],
) -> tuple[str, ...]:
    """Return unique tool names used by active agents."""
    ordered_tools: list[str] = []
    seen_tools: set[str] = set()

    for definition in definitions:
        for tool_name in definition.tools:
            if tool_name in seen_tools:
                continue
            ordered_tools.append(tool_name)
            seen_tools.add(tool_name)

    return tuple(ordered_tools)


def _select_required_agents(
    raw_configuration: dict[str, Any],
    required_agent_names: Iterable[str],
) -> dict[str, Any]:
    """Keep only agent records referenced by the active workflow."""
    raw_agents = raw_configuration.get("agents")
    if not isinstance(raw_agents, list):
        raise ValueError("agents.yaml must contain an 'agents' list")

    required_names = tuple(dict.fromkeys(required_agent_names))
    selected_agents: dict[str, dict[str, Any]] = {}
    duplicate_names: set[str] = set()

    for raw_agent in raw_agents:
        if not isinstance(raw_agent, dict):
            continue

        agent_name = raw_agent.get("name")
        if not isinstance(agent_name, str) or agent_name not in required_names:
            continue
        if agent_name in selected_agents:
            duplicate_names.add(agent_name)
        selected_agents[agent_name] = raw_agent

    missing_names = [name for name in required_names if name not in selected_agents]
    errors: list[str] = []
    if missing_names:
        errors.append(f"missing workflow agents in agents.yaml: {missing_names}")
    if duplicate_names:
        errors.append(f"duplicate workflow agents in agents.yaml: {sorted(duplicate_names)}")
    if errors:
        raise ValueError("Invalid agents.yaml configuration:\n- " + "\n- ".join(errors))

    return {"agents": [selected_agents[name] for name in required_names]}


__all__ = [
    "collect_agent_model_references",
    "collect_agent_tool_references",
    "collect_workflow_agent_names",
    "load_agent_definitions",
]
