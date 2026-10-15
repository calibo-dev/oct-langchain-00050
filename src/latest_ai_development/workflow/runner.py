"""Run configured workflow stages with registered agents."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from time import perf_counter
from typing import Any
from uuid import uuid4

from langsmith import traceable

from latest_ai_development.agents.registry import AgentRegistry
from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.context.runtime import ContextRuntime, ContextValidationError
from latest_ai_development.stages.schema import StageDefinition, WorkflowDefinition
from latest_ai_development.workflow.errors import WorkflowExecutionError
from latest_ai_development.workflow.prompt_builder import build_user_prompt
from latest_ai_development.workflow.response_parser import validate_agent_result
from latest_ai_development.workflow.trace_context import (
    build_agent_invoke_config,
    build_agent_trace_extra,
    build_stage_trace_extra,
    build_workflow_trace_extra,
)

logger = logging.getLogger(__name__)


class LatestAiDevelopmentWorkflow:
    """Execute the workflow configured in stages.yaml with registered agents."""

    def __init__(
        self,
        definition: WorkflowDefinition,
        agent_definitions: tuple[AgentDefinition, ...],
        agent_registry: AgentRegistry,
        context_configuration: ContextRuntime | None = None,
    ) -> None:
        """Store the workflow definition and already-created agent registry."""
        self.definition = definition
        self.agent_definitions = self._group_agent_definitions(agent_definitions)
        self.agent_registry = agent_registry
        self.context_configuration = context_configuration

    def kickoff(
        self,
        inputs: Mapping[str, Any],
        flow_run_id: str | None = None,
        *,
        context_inputs: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Run the configured workflow synchronously."""
        run_id = str(flow_run_id or uuid4().hex[:12]).strip() or uuid4().hex[:12]
        context = None
        if self.context_configuration is not None:
            context = self.context_configuration.resolve(context_inputs)
        elif context_inputs is not None:
            raise ContextValidationError("Runtime context is not configured")

        return self._kickoff_traced(
            inputs,
            run_id,
            context,
            langsmith_extra=build_workflow_trace_extra(self.definition.name, run_id),
        )

    def required_inputs(self) -> tuple[str, ...]:
        """Return the initial inputs explicitly declared by the workflow."""
        return tuple(self.definition.inputs)

    @traceable(run_type="chain")
    def _kickoff_traced(
        self,
        inputs: Mapping[str, Any],
        flow_run_id: str,
        context: Any = None,
    ) -> dict[str, str]:
        """Run the workflow inside one LangSmith parent trace."""
        values = dict(inputs)
        self._validate_request_inputs(values)

        logger.info(
            "Workflow started | flow_run_id=%s | workflow=%s",
            flow_run_id,
            self.definition.name,
        )
        workflow_started_at = perf_counter()

        for stage in self.definition.stages:
            stage_outputs = self._run_stage(
                stage,
                values,
                flow_run_id,
                context,
                langsmith_extra=build_stage_trace_extra(
                    self.definition.name,
                    stage,
                    flow_run_id,
                ),
            )
            values.update(stage_outputs)

        result = self._build_final_response(values)
        logger.info(
            "Workflow completed | flow_run_id=%s | workflow=%s | elapsed=%.2fs",
            flow_run_id,
            self.definition.name,
            perf_counter() - workflow_started_at,
        )
        return result

    @traceable(run_type="chain")
    def _run_stage(
        self,
        stage: StageDefinition,
        values: Mapping[str, Any],
        flow_run_id: str,
        context: Any = None,
    ) -> dict[str, Any]:
        """Run one workflow stage inside a LangSmith child trace."""
        self._validate_stage_inputs(stage, values)
        stage_started_at = perf_counter()
        stage_values = dict(values)

        logger.info(
            "Stage started | flow_run_id=%s | stage=%s | execution=%s",
            flow_run_id,
            stage.name,
            stage.execution,
        )

        if stage.execution == "parallel":
            produced_values = self._run_parallel_stage(stage, stage_values, flow_run_id, context)
        else:
            produced_values = self._run_sequential_stage(stage, stage_values, flow_run_id, context)

        stage_values.update(produced_values)

        self._validate_stage_outputs(stage, stage_values)

        logger.info(
            "Stage completed | flow_run_id=%s | stage=%s | elapsed=%.2fs",
            flow_run_id,
            stage.name,
            perf_counter() - stage_started_at,
        )
        return produced_values

    def _run_parallel_stage(
        self,
        stage: StageDefinition,
        stage_values: dict[str, Any],
        flow_run_id: str,
        context: Any = None,
    ) -> dict[str, Any]:
        """Run every agent in a stage at the same time and collect outputs."""
        stage_inputs = dict(stage_values)
        produced_values: dict[str, Any] = {}

        with ThreadPoolExecutor(max_workers=len(stage.agents)) as executor:
            futures = []
            for agent_name in stage.agents:
                future = executor.submit(
                    copy_context().run,
                    self._run_agent_with_trace,
                    agent_name,
                    stage_inputs,
                    stage.name,
                    flow_run_id,
                    context,
                )
                futures.append(future)

            for future in futures:
                agent_outputs = future.result()
                produced_values.update(agent_outputs)

        return produced_values

    def _run_sequential_stage(
        self,
        stage: StageDefinition,
        stage_values: dict[str, Any],
        flow_run_id: str,
        context: Any = None,
    ) -> dict[str, Any]:
        """Run stage agents one by one and pass each output to the next agent."""
        produced_values: dict[str, Any] = {}

        for agent_name in stage.agents:
            agent_outputs = self._run_agent_with_trace(
                agent_name,
                stage_values,
                stage.name,
                flow_run_id,
                context,
            )
            produced_values.update(agent_outputs)
            stage_values.update(agent_outputs)

        return produced_values

    def _run_agent_with_trace(
        self,
        agent_name: str,
        values: Mapping[str, Any],
        stage_name: str,
        flow_run_id: str,
        context: Any = None,
    ) -> dict[str, Any]:
        """Run one agent with clear LangSmith trace metadata."""
        return self._run_agent(
            agent_name,
            values,
            stage_name,
            flow_run_id,
            context,
            langsmith_extra=build_agent_trace_extra(
                self.definition.name,
                stage_name,
                agent_name,
                flow_run_id,
            ),
        )

    @traceable(run_type="chain")
    def _run_agent(
        self,
        agent_name: str,
        values: Mapping[str, Any],
        stage_name: str,
        flow_run_id: str,
        context: Any = None,
    ) -> dict[str, Any]:
        """Run one agent inside a LangSmith child trace."""
        definition = self.agent_definitions[agent_name]
        agent = self.agent_registry.get(agent_name)
        prompt = build_user_prompt(definition, values)
        agent_config = build_agent_invoke_config(
            self.definition.name,
            stage_name,
            agent_name,
            flow_run_id,
        )

        try:
            return agent.invoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config=agent_config,
                validate_result=lambda result: validate_agent_result(definition, result, values),
                **({"context": context} if context is not None else {}),
            )
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            raise WorkflowExecutionError(
                f"Stage '{stage_name}', agent '{agent_name}' failed: {reason}"
            ) from exc

    def _validate_request_inputs(self, values: Mapping[str, Any]) -> None:
        """Check that the request contains inputs required by starting stages."""
        missing_inputs: list[str] = []
        for input_name in self.required_inputs():
            if input_name not in values:
                missing_inputs.append(input_name)

        if missing_inputs:
            raise WorkflowExecutionError(
                f"Workflow '{self.definition.name}' is missing inputs: {missing_inputs}"
            )

    @staticmethod
    def _validate_stage_inputs(
        stage: StageDefinition,
        values: Mapping[str, Any],
    ) -> None:
        """Check that all inputs needed by one stage are available."""
        missing_inputs: list[str] = []
        for name in stage.inputs:
            if name not in values:
                missing_inputs.append(name)

        if missing_inputs:
            raise WorkflowExecutionError(
                f"Stage '{stage.name}' is missing inputs: {missing_inputs}"
            )

    @staticmethod
    def _validate_stage_outputs(
        stage: StageDefinition,
        values: Mapping[str, Any],
    ) -> None:
        """Check that a stage produced every output declared in stages.yaml."""
        missing_outputs: list[str] = []
        for output_name in stage.outputs:
            if output_name not in values:
                missing_outputs.append(output_name)

        if missing_outputs:
            raise WorkflowExecutionError(
                f"Stage '{stage.name}' did not produce required outputs: {missing_outputs}"
            )

    @staticmethod
    def _group_agent_definitions(
        agent_definitions: tuple[AgentDefinition, ...],
    ) -> dict[str, AgentDefinition]:
        """Create a lookup table so agents can be found quickly by name."""
        definitions_by_name: dict[str, AgentDefinition] = {}
        for definition in agent_definitions:
            definitions_by_name[definition.name] = definition
        return definitions_by_name

    def _build_final_response(self, values: Mapping[str, Any]) -> dict[str, str]:
        """Collect final workflow outputs into the API response."""
        response: dict[str, str] = {}
        for output_name in self._workflow_output_names():
            response[output_name] = str(values[output_name])
        return response

    def _workflow_output_names(self) -> tuple[str, ...]:
        """Return outputs from final stages in YAML order."""
        dependency_names: set[str] = set()
        for stage in self.definition.stages:
            dependency_names.update(stage.depends_on)

        output_names: list[str] = []
        for stage in self.definition.stages:
            if stage.name in dependency_names:
                continue
            output_names.extend(stage.outputs)

        unique_output_names: list[str] = []
        seen_output_names: set[str] = set()
        for output_name in output_names:
            if output_name in seen_output_names:
                continue
            unique_output_names.append(output_name)
            seen_output_names.add(output_name)

        return tuple(unique_output_names)
