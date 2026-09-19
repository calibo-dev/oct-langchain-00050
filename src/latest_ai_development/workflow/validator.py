"""Run validation that spans the complete workflow configuration."""

from __future__ import annotations

import logging

from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.agents.validator import validate_agents_configuration
from latest_ai_development.models.schema import ModelsConfiguration
from latest_ai_development.stages.schema import WorkflowDefinition
from latest_ai_development.stages.validator import validate_stages_configuration
from latest_ai_development.tools.schema import ToolsConfiguration

logger = logging.getLogger(__name__)


def validate_workflow_configuration(
    workflow: WorkflowDefinition,
    agent_definitions: tuple[AgentDefinition, ...],
    models_configuration: ModelsConfiguration,
    tools_configuration: ToolsConfiguration,
) -> None:
    """Validate references across agents, models, and workflow stages."""
    logger.debug("Workflow configuration validation started")

    # Agent validation runs first because stage validation depends on valid agents.
    validate_agents_configuration(
        agent_definitions,
        models_configuration,
        tools_configuration,
    )
    validate_stages_configuration(workflow, agent_definitions)

    logger.debug("Workflow configuration validation completed")
