"""Build prompts for configured workflow agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from latest_ai_development.agents.schema import AgentDefinition


def build_user_prompt(
    definition: AgentDefinition,
    values: Mapping[str, Any],
) -> str:
    """Build the user message sent to one agent.

    The system prompt is already attached when the LangChain agent is created.
    This function only sends the current workflow values needed by the agent.
    """
    input_sections: list[str] = []
    for input_name in definition.inputs:
        input_sections.append(f"{input_name}:\n{values[input_name]}")

    output_instruction = _build_output_instruction(definition)

    return (
        "Use the following workflow inputs:\n\n"
        + "\n\n".join(input_sections)
        + f"\n\n{output_instruction}"
    )


def _build_output_instruction(definition: AgentDefinition) -> str:
    """Tell the agent exactly what output shape the workflow expects."""
    output_names = ", ".join(definition.outputs)

    return (
        "Return only a valid JSON object containing exactly these keys: "
        + output_names
        + ". Do not include markdown, code fences, or extra text."
    )
