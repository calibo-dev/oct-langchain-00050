"""Exercise startup contracts and execution evidence without external services."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from latest_ai_development.agents.config import load_agent_definitions
from latest_ai_development.agents.registry import AgentRegistry
from latest_ai_development.agents.runtime import AgentRuntime
from latest_ai_development.application import create_app
from latest_ai_development.core.settings import Settings
from latest_ai_development.core.settings_validator import validate_settings_configuration
from latest_ai_development.stages.config import load_workflow_definition
from latest_ai_development.stages.validator import validate_stages_configuration
from latest_ai_development.workflow import LatestAiDevelopmentWorkflow, WorkflowExecutionError


def test_current_workflow_contracts_are_valid():
    definition = load_workflow_definition()
    agents = load_agent_definitions(tuple(a for s in definition.stages for a in s.agents))
    validate_stages_configuration(definition, agents)


def test_required_settings_have_no_code_defaults():
    assert all(
        field.is_required()
        for name, field in Settings.model_fields.items()
        if name != "ollama_base_url"
    )
    assert Settings.model_fields["ollama_base_url"].default is None
    with pytest.raises(ValidationError):
        Settings.model_validate({})


@pytest.mark.parametrize("url", [None, "", "   "])
def test_active_ollama_requires_an_environment_url(url):
    from latest_ai_development.models.provider_builders import build_ollama_llm

    with pytest.raises(ValueError, match="OLLAMA_BASE_URL is required"):
        build_ollama_llm(SimpleNamespace(ollama_base_url=url), "example", {})


def test_settings_errors_are_aggregated():
    settings = SimpleNamespace(
        context="",
        cloud_provider="AWS",
        aws_region="",
        azure_key_vault_url="",
        api_root_path="bad",
        port=0,
        api_host="",
        log_level="unknown",
    )
    with pytest.raises(ValueError) as error:
        validate_settings_configuration(settings)
    for name in ["CONTEXT", "AWS_REGION", "API_ROOT_PATH", "PORT", "API_HOST", "LOG_LEVEL"]:
        assert name in str(error.value)


@pytest.mark.parametrize("include_tool", [False, True])
def test_required_tool_evidence(include_tool):
    definition = load_workflow_definition()
    agents = load_agent_definitions(("metadata_fetching_agent",))
    messages = [{"role": "assistant", "content": '{"country_table_metadata": []}'}]
    if include_tool:
        messages.insert(0, {"role": "tool", "name": "country_data_agentic_tool", "content": "[]"})
    runtime = Mock()
    runtime.invoke.return_value = {"messages": messages}
    workflow = LatestAiDevelopmentWorkflow(
        definition, agents, AgentRegistry({"metadata_fetching_agent": runtime})
    )
    if include_tool:
        assert workflow._run_agent(
            "metadata_fetching_agent",
            {"user_natural_language_query": "hi"},
            "fetch_metadata",
            "test",
        ) == {"country_table_metadata": []}
    else:
        with pytest.raises(WorkflowExecutionError, match="required tool execution is missing"):
            workflow._run_agent(
                "metadata_fetching_agent",
                {"user_natural_language_query": "hi"},
                "fetch_metadata",
                "test",
            )


def test_fallback_uses_second_agent_after_failure():
    primary, fallback = Mock(), Mock()
    primary.invoke.side_effect = RuntimeError("provider unavailable")
    fallback.invoke.return_value = {"messages": []}
    runtime = AgentRuntime("agent", (primary, fallback), ("primary", "fallback"))
    assert runtime.invoke({"messages": []}, config={}) == {"messages": []}
    assert fallback.invoke.call_args.kwargs["config"]["metadata"]["is_fallback_model"]


def test_application_routes_and_shutdown(monkeypatch):
    definition = load_workflow_definition()
    connections = Mock()
    workflow = Mock()
    workflow.kickoff.return_value = {"response": "ok"}
    container = SimpleNamespace(
        settings=SimpleNamespace(api_root_path="/testing", app_name="test"),
        workflow_definition=definition,
        workflow=workflow,
        connection_registry=connections,
        agent_registry=SimpleNamespace(count=lambda: 5),
        model_registry=SimpleNamespace(count=lambda: 2),
    )
    monkeypatch.setattr(
        "latest_ai_development.application.get_application_container", lambda: container
    )
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json()["agents"] == 5
        response = client.post(
            f"/{definition.name}", json={"user_natural_language_query": "count countries"}
        )
        assert response.json() == {"response": "ok"}
    connections.close.assert_called_once()
