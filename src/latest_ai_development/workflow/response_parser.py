"""Parse LangChain agent responses into workflow output values."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from latest_ai_development.agents.schema import AgentDefinition


def extract_response_text(result: Any) -> str:
    """Read the final text content from a LangChain agent result."""
    if not isinstance(result, Mapping):
        raise ValueError("agent returned an invalid result")

    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("agent returned no messages")

    last_message = messages[-1]
    content = (
        last_message.get("content")
        if isinstance(last_message, Mapping)
        else getattr(last_message, "content", None)
    )

    if isinstance(content, str) and content.strip():
        return content.strip()

    if isinstance(content, list):
        response_text = _extract_text_blocks(content)
        if response_text:
            return response_text

    raise ValueError("agent returned an empty text response")


def extract_agent_outputs(
    definition: AgentDefinition,
    response_text: str,
) -> dict[str, Any]:
    """Convert one agent response into the configured workflow outputs."""
    payload = _load_json_object(definition, response_text)
    missing_outputs: list[str] = []
    for name in definition.outputs:
        if name not in payload:
            missing_outputs.append(name)

    if missing_outputs:
        raise ValueError(f"agent '{definition.name}' omitted configured outputs: {missing_outputs}")

    outputs: dict[str, Any] = {}
    for name in definition.outputs:
        outputs[name] = payload[name]
    return outputs


def _extract_text_blocks(content: list[Any]) -> str:
    """Handle providers that return text as a list of content blocks."""
    text_parts: list[str] = []

    for block in content:
        if isinstance(block, str):
            text_parts.append(block)
        elif isinstance(block, Mapping):
            text_parts.append(str(block.get("text", "")))

    return "\n".join(text_parts).strip()


def _load_json_object(
    definition: AgentDefinition,
    response_text: str,
) -> Mapping[str, Any]:
    """Load a multi-output agent response as a JSON object."""
    try:
        payload = json.loads(_strip_json_code_fence(response_text))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"agent '{definition.name}' must return a JSON object for outputs {definition.outputs}"
        ) from exc

    if not isinstance(payload, Mapping):
        raise ValueError(f"agent '{definition.name}' returned a non-object JSON value")

    return payload


def _strip_json_code_fence(response_text: str) -> str:
    """Accept JSON wrapped in a markdown code fence."""
    lines = response_text.strip().splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
        if lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return response_text
