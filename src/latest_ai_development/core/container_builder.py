"""Build validated application objects during FastAPI startup."""

from __future__ import annotations

import logging

from latest_ai_development.agents.config import (
    collect_agent_model_references,
    collect_agent_tool_references,
    collect_workflow_agent_names,
    load_agent_definitions,
)
from latest_ai_development.agents.factory import build_agent_registry
from latest_ai_development.agents.registry import AgentRegistry
from latest_ai_development.agents.schema import AgentDefinition, AgentModel
from latest_ai_development.connections.config import load_connections_configuration
from latest_ai_development.connections.factory import build_connection_registry
from latest_ai_development.connections.registry import ConnectionRegistry
from latest_ai_development.connections.schema import ConnectionConfigurations
from latest_ai_development.core.container import ApplicationContainer
from latest_ai_development.core.logging_config import configure_logging
from latest_ai_development.core.settings import Settings, get_settings
from latest_ai_development.core.settings_validator import validate_settings_configuration
from latest_ai_development.models.config import load_models_configuration
from latest_ai_development.models.factory import build_model_registry
from latest_ai_development.models.registry import ModelRegistry
from latest_ai_development.models.schema import ModelsConfiguration
from latest_ai_development.stages.config import load_workflow_definition
from latest_ai_development.stages.schema import WorkflowDefinition
from latest_ai_development.tools.config import (
    collect_connection_names,
    load_tools_configuration,
)
from latest_ai_development.tools.factory import build_tool_registry
from latest_ai_development.tools.registry import ToolRegistry
from latest_ai_development.tools.schema import ToolsConfiguration
from latest_ai_development.workflow import LatestAiDevelopmentWorkflow
from latest_ai_development.workflow.validator import validate_workflow_configuration

logger = logging.getLogger(__name__)


class ApplicationContainerBuilder:
    """Load configuration and create runtime dependencies in order."""

    def build(self) -> ApplicationContainer:
        """Build the complete application container."""
        logger.info("Application startup started")

        settings = self._load_settings()
        logger.info("\n\nLoaded settings:\n%s", settings)
        workflow_definition = self._load_workflow()
        logger.info("\n\nLoaded workflow definition:\n%s", workflow_definition)
        agent_definitions = self._load_active_agents(workflow_definition)
        logger.info("\n\nLoaded active agent definitions:\n%s", agent_definitions)
        model_references = self._find_active_models(agent_definitions)
        logger.info("\n\n Resolved active model references:\n%s", model_references)
        tool_names = self._find_active_tools(agent_definitions)
        logger.info("\n\n Resolved active tool names:\n%s", tool_names)

        models_configuration = self._load_active_models(model_references)
        logger.info("\n\nLoaded active models configuration:\n%s", models_configuration)
        tools_configuration = self._load_active_tools(tool_names)
        logger.info("\n\nLoaded active tools configuration:\n%s", tools_configuration)
        connections_configuration = self._load_active_connections(tools_configuration)
        logger.info("Loaded active connections configuration:\n%s", connections_configuration)

        self._validate_workflow(
            workflow_definition,
            agent_definitions,
            models_configuration,
            tools_configuration,
        )

        connection_registry = self._build_connections(connections_configuration)
        logger.info("\n\nBuilt connection registry:\n%s", connection_registry)
        model_registry = self._build_models(
            settings,
            models_configuration,
            model_references,
        )
        logger.info("\n\nBuilt model registry:\n%s", model_registry)
        tool_registry = self._build_tools(
            settings,
            tools_configuration,
            connection_registry,
        )
        logger.info("\n\nBuilt tool registry:\n%s", tool_registry)
        agent_registry = self._build_agents(
            agent_definitions,
            model_registry,
            tool_registry,
        )
        logger.info("\n\nBuilt agent registry:\n%s", agent_registry)
        workflow = self._build_workflow(
            workflow_definition,
            agent_definitions,
            agent_registry,
        )
        logger.info("\n\nBuilt workflow:\n%s", workflow)

        logger.info("Application startup completed")
        return ApplicationContainer(
            settings=settings,
            connection_registry=connection_registry,
            model_registry=model_registry,
            tool_registry=tool_registry,
            agent_definitions=agent_definitions,
            agent_registry=agent_registry,
            workflow_definition=workflow_definition,
            workflow=workflow,
        )

    def _load_settings(self) -> Settings:
        """Load and validate environment settings before other startup work."""
        settings = get_settings()
        configure_logging(settings.log_level)
        validate_settings_configuration(settings)
        return settings

    def _load_workflow(self) -> WorkflowDefinition:
        """Load stages.yaml because it determines which agents are active."""
        workflow_definition = load_workflow_definition()
        logger.info(
            "Workflow loaded workflow=%s stages=%s",
            workflow_definition.name,
            len(workflow_definition.stages),
        )
        return workflow_definition

    def _load_active_agents(
        self,
        workflow_definition: WorkflowDefinition,
    ) -> tuple[AgentDefinition, ...]:
        """Load only agents referenced by workflow stages."""
        agents_by_stage: list[list[str]] = []

        for stage in workflow_definition.stages:
            stage_agent_names = stage.agents
            agents_by_stage.append(stage_agent_names)

        active_agent_names = collect_workflow_agent_names(agents_by_stage)
        agent_definitions = load_agent_definitions(active_agent_names)
        logger.info("Active agents loaded count=%s", len(agent_definitions))
        return agent_definitions

    def _find_active_models(
        self,
        agent_definitions: tuple[AgentDefinition, ...],
    ) -> tuple[AgentModel, ...]:
        """Collect primary and fallback models used by active agents."""
        model_references = collect_agent_model_references(agent_definitions)
        logger.info("Active models resolved count=%s", len(model_references))
        return model_references

    def _find_active_tools(
        self,
        agent_definitions: tuple[AgentDefinition, ...],
    ) -> tuple[str, ...]:
        """Collect tool names used by active agents."""
        tool_names = collect_agent_tool_references(agent_definitions)
        logger.info("Active tools resolved count=%s", len(tool_names))
        return tool_names

    def _load_active_models(
        self,
        model_references: tuple[AgentModel, ...],
    ) -> ModelsConfiguration:
        """Load validated configuration for active models."""
        return load_models_configuration(model_references)

    def _load_active_tools(
        self,
        tool_names: tuple[str, ...],
    ) -> ToolsConfiguration:
        """Load validated configuration for active tools."""
        return load_tools_configuration(tool_names)

    def _load_active_connections(
        self,
        tools_configuration: ToolsConfiguration,
    ) -> ConnectionConfigurations:
        """Load connections referenced by active tools."""
        connection_names = collect_connection_names(tools_configuration)
        return load_connections_configuration(connection_names)

    def _validate_workflow(
        self,
        workflow_definition: WorkflowDefinition,
        agent_definitions: tuple[AgentDefinition, ...],
        models_configuration: ModelsConfiguration,
        tools_configuration: ToolsConfiguration,
    ) -> None:
        """Validate references before constructing external runtime objects."""
        validate_workflow_configuration(
            workflow_definition,
            agent_definitions,
            models_configuration,
            tools_configuration,
        )

    def _build_connections(
        self,
        configuration: ConnectionConfigurations,
    ) -> ConnectionRegistry:
        """Create connection managers used by active tools."""
        return build_connection_registry(configuration)

    def _build_models(
        self,
        settings: Settings,
        configuration: ModelsConfiguration,
        model_references: tuple[AgentModel, ...],
    ) -> ModelRegistry:
        """Create runtime LLM objects used by active agents."""
        registry = build_model_registry(settings, configuration, model_references)
        logger.info("Model objects created count=%s", registry.count())
        return registry

    def _build_tools(
        self,
        settings: Settings,
        configuration: ToolsConfiguration,
        connection_registry: ConnectionRegistry,
    ) -> ToolRegistry:
        """Create runtime LangChain tools used by active agents."""
        registry = build_tool_registry(
            settings,
            configuration,
            connection_registry,
        )
        logger.info("Tool objects created count=%s", registry.count())
        return registry

    def _build_agents(
        self,
        definitions: tuple[AgentDefinition, ...],
        model_registry: ModelRegistry,
        tool_registry: ToolRegistry,
    ) -> AgentRegistry:
        """Create runtime LangChain agents."""
        registry = build_agent_registry(
            definitions,
            model_registry,
            tool_registry,
        )
        logger.info("Agent objects created count=%s", registry.count())
        return registry

    def _build_workflow(
        self,
        definition: WorkflowDefinition,
        agent_definitions: tuple[AgentDefinition, ...],
        agent_registry: AgentRegistry,
    ) -> LatestAiDevelopmentWorkflow:
        """Create the workflow used by API requests."""
        return LatestAiDevelopmentWorkflow(
            definition=definition,
            agent_definitions=agent_definitions,
            agent_registry=agent_registry,
        )
