"""Build validated application objects during FastAPI startup."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from latest_ai_development.agents.config import (
    collect_agent_model_references,
    collect_agent_tool_references,
    collect_workflow_agent_names,
    load_agent_definitions,
)
from latest_ai_development.agents.factory import build_agent_registry
from latest_ai_development.agents.registry import AgentRegistry
from latest_ai_development.agents.schema import AgentDefinition, AgentModel
from latest_ai_development.context.config import load_context_configuration
from latest_ai_development.context.runtime import ContextRuntime
from latest_ai_development.core.container import ApplicationContainer
from latest_ai_development.core.errors import ToolExecutionError
from latest_ai_development.core.logging_config import configure_logging
from latest_ai_development.core.settings import CONFIG_DIR, Settings, get_settings
from latest_ai_development.core.settings_validator import validate_settings_configuration
from latest_ai_development.models.config import load_models_configuration
from latest_ai_development.models.factory import build_model_registry
from latest_ai_development.models.registry import ModelRegistry
from latest_ai_development.models.schema import ModelsConfiguration
from latest_ai_development.stages.config import load_workflow_definition
from latest_ai_development.stages.schema import WorkflowDefinition
from latest_ai_development.tracking import initialize_langsmith_tracing
from latest_ai_development.workflow import LatestAiDevelopmentWorkflow
from latest_ai_development.workflow.validator import validate_workflow_configuration

logger = logging.getLogger(__name__)


def _resolve_tool_secret(name: str, settings: Settings | None = None) -> str | None:
    """Provide this template's secret backend to the portable tool registry."""
    from latest_ai_development.core.secrets_manager import SecretsManager

    return SecretsManager(settings).get_secret(name)


def _adapt_tool(implementation: Any) -> BaseTool:
    """Keep LangChain wrapping and fail-fast errors outside shared provider files."""
    if isinstance(implementation, BaseTool):
        return implementation
    if not callable(getattr(implementation, "execute", None)) or not getattr(
        implementation, "args_schema", None
    ):
        raise TypeError("Tool factories must return a native tool or an executable implementation")

    def execute(**arguments: Any) -> str:
        try:
            return implementation.execute(**arguments)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(implementation.name, str(exc)) from exc

    return StructuredTool.from_function(
        func=execute,
        name=implementation.name,
        description=implementation.description,
        args_schema=implementation.args_schema,
        tags=getattr(implementation, "tags", []),
        metadata=getattr(implementation, "metadata", {}),
    )


class ApplicationContainerBuilder:
    """Load configuration and create runtime dependencies in order."""

    def build(self) -> ApplicationContainer:
        """Build the complete application container."""
        logger.info("Application startup started")

        settings = self._load_settings()
        initialize_langsmith_tracing()
        logger.debug("\n\nLoaded settings:\n%s", settings)
        workflow_definition = self._load_workflow()
        logger.debug("\n\nLoaded workflow definition:\n%s", workflow_definition)
        agent_definitions = self._load_active_agents(workflow_definition)
        context_configuration = load_context_configuration()
        if context_configuration is not None:
            if "context" in workflow_definition.inputs:
                raise ValueError("Workflow input 'context' conflicts with enabled runtime context")
            for definition in agent_definitions:
                context_configuration.validate_prompt(definition.system_prompt)
        logger.debug("\n\nLoaded active agent definitions:\n%s", agent_definitions)
        model_references = self._find_active_models(agent_definitions)
        logger.debug("\n\nResolved active model references:\n%s", model_references)
        tool_names = self._find_active_tools(agent_definitions)
        logger.debug("\n\nResolved active tool names:\n%s", tool_names)

        models_configuration = self._load_active_models(model_references)
        logger.debug("\n\nLoaded active models configuration:\n%s", models_configuration)
        tool_registry = self._load_active_tools(tool_names, settings)
        logger.debug("\n\nBuilt active tool registry:\n%s", tool_registry)

        try:
            self._validate_workflow(
                workflow_definition,
                agent_definitions,
                models_configuration,
                tool_registry,
            )
            model_registry = self._build_models(
                settings,
                models_configuration,
                model_references,
            )
            logger.debug("\n\nBuilt model registry:\n%s", model_registry)
            agent_registry = self._build_agents(
                agent_definitions,
                model_registry,
                tool_registry,
                context_configuration,
            )
            logger.debug("\n\nBuilt agent registry:\n%s", agent_registry)
            workflow = self._build_workflow(
                workflow_definition,
                agent_definitions,
                agent_registry,
                context_configuration,
            )
            logger.debug("\n\nBuilt workflow:\n%s", workflow)
        except Exception:
            close = getattr(tool_registry, "close", None)
            if callable(close):
                close()
            raise

        logger.info("Application startup completed")
        return ApplicationContainer(
            settings=settings,
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
        settings: Settings | None = None,
    ) -> Mapping[str, Any]:
        """Build selected native tools and retain their shared resource owner."""
        if not tool_names:
            logger.info("No active tools configured")
            return {}

        try:
            from latest_ai_development.tools.tools_registry import build_tools_registry
        except ModuleNotFoundError as exc:
            if exc.name in {
                "latest_ai_development.tools",
                "latest_ai_development.tools.tools_registry",
            }:
                raise RuntimeError(
                    f"Tool runtime is missing for configured tools: {list(tool_names)}"
                ) from exc
            raise

        registry = build_tools_registry(
            tool_names,
            CONFIG_DIR,
            resolve_secret=lambda name: _resolve_tool_secret(name, settings),
            adapt_tool=_adapt_tool,
        )
        logger.info("Tool objects created count=%s", len(registry))
        return registry

    def _validate_workflow(
        self,
        workflow_definition: WorkflowDefinition,
        agent_definitions: tuple[AgentDefinition, ...],
        models_configuration: ModelsConfiguration,
        tool_registry: Mapping[str, Any],
    ) -> None:
        """Validate references before constructing external runtime objects."""
        validate_workflow_configuration(
            workflow_definition,
            agent_definitions,
            models_configuration,
            set(tool_registry),
        )

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

    def _build_agents(
        self,
        definitions: tuple[AgentDefinition, ...],
        model_registry: ModelRegistry,
        tool_registry: Mapping[str, Any],
        context_configuration: ContextRuntime | None = None,
    ) -> AgentRegistry:
        """Create runtime LangChain agents."""
        registry = build_agent_registry(
            definitions,
            model_registry,
            tool_registry,
            context_configuration,
        )
        logger.info("Agent objects created count=%s", registry.count())
        return registry

    def _build_workflow(
        self,
        definition: WorkflowDefinition,
        agent_definitions: tuple[AgentDefinition, ...],
        agent_registry: AgentRegistry,
        context_configuration: ContextRuntime | None = None,
    ) -> LatestAiDevelopmentWorkflow:
        """Create the workflow used by API requests."""
        return LatestAiDevelopmentWorkflow(
            definition=definition,
            agent_definitions=agent_definitions,
            agent_registry=agent_registry,
            context_configuration=context_configuration,
        )
