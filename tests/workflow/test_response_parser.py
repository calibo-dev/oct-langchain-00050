import json

import pytest

from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.workflow.response_parser import extract_agent_outputs


def test_single_output_agent_response_must_be_json() -> None:
    agent = AgentDefinition(
        name="title_generation_agent",
        model=[{"provider": "OpenAI", "modelId": "gpt-5.4-mini"}],
        inputs=["description", "mood"],
        outputs=["generated_title"],
        system_prompt="Generate a title.",
    )

    result = extract_agent_outputs(
        agent,
        json.dumps({"generated_title": "A Calm Guide to AI Development"}),
    )

    assert result == {"generated_title": "A Calm Guide to AI Development"}


def test_single_output_agent_rejects_plain_text() -> None:
    agent = AgentDefinition(
        name="title_generation_agent",
        model=[{"provider": "OpenAI", "modelId": "gpt-5.4-mini"}],
        inputs=["description", "mood"],
        outputs=["generated_title"],
        system_prompt="Generate a title.",
    )

    with pytest.raises(ValueError, match="must return a JSON object"):
        extract_agent_outputs(agent, "A Calm Guide to AI Development")


def test_multi_output_agent_rejects_missing_json_key() -> None:
    agent = AgentDefinition(
        name="reviewer_agent",
        model=[{"provider": "OpenAI", "modelId": "gpt-5.4-mini"}],
        inputs=["generated_title"],
        outputs=["review_status", "review_summary"],
        system_prompt="Review the content.",
    )

    with pytest.raises(ValueError, match="omitted configured outputs"):
        extract_agent_outputs(agent, json.dumps({"review_status": "approved"}))
