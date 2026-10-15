"""Validate how agents and stages are connected in a workflow."""

from __future__ import annotations

from collections.abc import Iterable

from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.stages.schema import StageDefinition, WorkflowDefinition


def _collect_dependency_outputs(
    stage_name: str,
    stages_by_name: dict[str, StageDefinition],
    visited: set[str] | None = None,
) -> set[str]:
    """Return outputs produced by a stage and all stages before it."""
    # ``visited`` prevents endless recursion if an invalid cycle reaches this helper.
    visited = set() if visited is None else visited
    if stage_name in visited:
        return set()
    visited.add(stage_name)

    stage = stages_by_name[stage_name]
    available_outputs = set(stage.outputs)
    for dependency_name in stage.depends_on:
        if dependency_name in stages_by_name:
            dependency_outputs = _collect_dependency_outputs(
                dependency_name,
                stages_by_name,
                visited,
            )
            available_outputs.update(dependency_outputs)
    return available_outputs


def _find_stage_agents(
    stage: StageDefinition,
    agents_by_name: dict[str, AgentDefinition],
    errors: list[str],
) -> list[AgentDefinition]:
    """Resolve a stage's agent names and record names that do not exist."""
    stage_agents: list[AgentDefinition] = []
    for agent_name in stage.agents:
        agent = agents_by_name.get(agent_name)
        if agent is None:
            errors.append(f"stage '{stage.name}' references unknown agent '{agent_name}'")
            continue
        stage_agents.append(agent)
    return stage_agents


def validate_stages_configuration(
    workflow: WorkflowDefinition,
    agent_definitions: Iterable[AgentDefinition],
) -> None:
    """Validate stage order and the data passed between configured agents."""
    agents_by_name = _group_agents_by_name(agent_definitions)
    stages_by_name = _group_stages_by_name(workflow.stages)
    workflow_inputs = set(workflow.inputs)
    previous_stage_names: set[str] = set()
    errors: list[str] = []

    # YAML order is execution order, so dependencies must already have appeared.
    for stage in workflow.stages:
        _validate_stage_dependencies(stage, stages_by_name, previous_stage_names, errors)
        stage_agents = _find_stage_agents(stage, agents_by_name, errors)
        _validate_stage_contract(stage, stage_agents, errors)
        _validate_stage_inputs_are_available(stage, stages_by_name, workflow_inputs, errors)

        previous_stage_names.add(stage.name)

    if errors:
        details = _format_errors(errors)
        raise ValueError(f"Stage configuration validation failed:\n{details}")


def _group_agents_by_name(
    agent_definitions: Iterable[AgentDefinition],
) -> dict[str, AgentDefinition]:
    """Create a lookup table for agents."""
    agents_by_name: dict[str, AgentDefinition] = {}
    for agent in agent_definitions:
        agents_by_name[agent.name] = agent
    return agents_by_name


def _group_stages_by_name(
    stages: Iterable[StageDefinition],
) -> dict[str, StageDefinition]:
    """Create a lookup table for stages."""
    stages_by_name: dict[str, StageDefinition] = {}
    for stage in stages:
        stages_by_name[stage.name] = stage
    return stages_by_name


def _format_errors(errors: list[str]) -> str:
    """Format validation errors as a readable bullet list."""
    lines: list[str] = []
    for error in errors:
        lines.append(f"- {error}")
    return "\n".join(lines)


def _validate_stage_dependencies(
    stage: StageDefinition,
    stages_by_name: dict[str, StageDefinition],
    previous_stage_names: set[str],
    errors: list[str],
) -> None:
    """Check that stage dependencies exist and come before the current stage."""
    for dependency_name in stage.depends_on:
        if dependency_name not in stages_by_name:
            errors.append(f"stage '{stage.name}' depends on unknown stage '{dependency_name}'")
        elif dependency_name not in previous_stage_names:
            errors.append(f"stage '{stage.name}' must appear after dependency '{dependency_name}'")


def _validate_stage_contract(
    stage: StageDefinition,
    stage_agents: list[AgentDefinition],
    errors: list[str],
) -> None:
    """Check that stage inputs/outputs match the agents inside that stage."""
    expected_inputs: set[str] = set()
    expected_outputs: set[str] = set()

    for agent in stage_agents:
        expected_inputs.update(agent.inputs)
        expected_outputs.update(agent.outputs)

    if set(stage.inputs) != expected_inputs:
        errors.append(
            f"stage '{stage.name}' inputs do not match its agents: "
            f"expected {sorted(expected_inputs)}, got {sorted(stage.inputs)}"
        )
    if set(stage.outputs) != expected_outputs:
        errors.append(
            f"stage '{stage.name}' outputs do not match its agents: "
            f"expected {sorted(expected_outputs)}, got {sorted(stage.outputs)}"
        )


def _validate_stage_inputs_are_available(
    stage: StageDefinition,
    stages_by_name: dict[str, StageDefinition],
    workflow_inputs: set[str],
    errors: list[str],
) -> None:
    """Check that a stage only uses original inputs or dependency outputs."""
    available_inputs = set(workflow_inputs)
    for dependency_name in stage.depends_on:
        if dependency_name in stages_by_name:
            available_inputs.update(_collect_dependency_outputs(dependency_name, stages_by_name))

    missing_inputs = set(stage.inputs) - available_inputs
    if missing_inputs:
        errors.append(
            f"stage '{stage.name}' has inputs not declared in workflow.inputs "
            "or produced by its dependencies: "
            f"{sorted(missing_inputs)}"
        )
