from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from latest_ai_development.api import build_api_router
from latest_ai_development.api.error_handlers import register_error_handlers
from latest_ai_development.stages.schema import WorkflowDefinition
from latest_ai_development.stages.validator import validate_stages_configuration
from latest_ai_development.workflow import WorkflowExecutionError


def make_definition(name="sample_workflow", inputs=None):
    return WorkflowDefinition.model_validate(
        {
            "name": name,
            "execution": "sequential",
            "inputs": inputs if inputs is not None else ["question", "context"],
            "stages": [
                {
                    "name": "answer",
                    "execution": "sequential",
                    "agents": ["agent"],
                    "inputs": ["question", "context"],
                    "outputs": ["response"],
                }
            ],
        }
    )


def make_client(definition, failure=None):
    calls = []

    def kickoff(inputs, flow_run_id):
        assert flow_run_id
        calls.append(inputs)
        if failure:
            raise failure
        return {"response": "done"}

    app = FastAPI()
    register_error_handlers(app)
    app.state.workflow = SimpleNamespace(kickoff=kickoff)
    app.include_router(build_api_router(definition))
    return TestClient(app), calls


def test_route_and_openapi_follow_configuration():
    for name, inputs in [
        ("sample_workflow", ["question", "context"]),
        ("another_workflow", ["description"]),
    ]:
        client, calls = make_client(make_definition(name, inputs))
        payload = dict.fromkeys(inputs, "valid input")
        assert client.post(f"/{name}", json=payload).json() == {"response": "done"}
        assert calls == [payload]
        assert client.post("/ask", json=payload).status_code == 404
        schema = client.get("/openapi.json").json()
        operation = schema["paths"][f"/{name}"]["post"]
        ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        body = schema["components"]["schemas"][ref.rsplit("/", 1)[1]]
        assert body["required"] == inputs
        assert body["additionalProperties"] is False
        assert all(field["type"] == "string" for field in body["properties"].values())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": "hello"},
        *[
            {"question": value, "context": "valid"}
            for value in [None, 123, True, [], {}, "", " \n\t"]
        ],
        {"question": "hello", "context": "valid", "unknown": "extra"},
    ],
)
def test_invalid_payload_does_not_execute_workflow(payload):
    client, calls = make_client(make_definition())
    response = client.post("/sample_workflow", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "request_validation_failed"
    assert calls == []


@pytest.mark.parametrize(
    "failure, status",
    [
        (WorkflowExecutionError("Invalid output"), 502),
        (RuntimeError("secret"), 500),
    ],
)
def test_execution_errors_keep_existing_response_format(failure, status):
    client, _ = make_client(make_definition(), failure)
    response = client.post("/sample_workflow", json={"question": "hi", "context": "ok"})
    assert response.status_code == status
    assert response.json()["error"] == "workflow_execution_failed"
    assert "secret" not in response.text


def test_start_stage_requires_declared_inputs():
    definition = make_definition(inputs=["question"])
    agent = SimpleNamespace(name="agent", inputs=["question", "context"], outputs=["response"])
    with pytest.raises(ValueError, match="not declared in workflow.inputs"):
        validate_stages_configuration(definition, [agent])


@pytest.mark.parametrize("name", ["", "bad name", "_private", "model_dump", "class"])
def test_invalid_request_field_names_rejected(name):
    with pytest.raises(ValidationError):
        make_definition(inputs=[name])


def test_workflow_inputs_must_be_explicit():
    configuration = make_definition().model_dump()
    del configuration["inputs"]
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(configuration)
