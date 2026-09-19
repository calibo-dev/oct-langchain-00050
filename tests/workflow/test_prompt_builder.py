from latest_ai_development.agents.schema import AgentDefinition
from latest_ai_development.workflow.prompt_builder import build_user_prompt


def test_prompt_builder_always_requests_json_output() -> None:
    agent = AgentDefinition(
        name="title_generation_agent",
        model=[{"provider": "OpenAI", "modelId": "gpt-5.4-mini"}],
        inputs=["description", "mood"],
        outputs=["generated_title"],
        system_prompt="Generate a title.",
    )

    prompt = build_user_prompt(
        agent,
        {
            "description": "Write about AI development.",
            "mood": "calm",
        },
    )

    assert "Return only a valid JSON object" in prompt
    assert "generated_title" in prompt
    assert "Do not include markdown" in prompt
