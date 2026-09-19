"""Dispatch validation to the schema owned by each tool connector."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from latest_ai_development.tools.schema import BaseToolDefinition, ToolsConfiguration
from latest_ai_development.tools.snowflake.validator import (
    validate_snowflake_tool_definition,
)

ToolDefinitionValidator = Callable[[Mapping[str, Any]], BaseToolDefinition]

# Adding another connector requires its own schema/validator and one entry here.
TOOL_DEFINITION_VALIDATORS: dict[str, ToolDefinitionValidator] = {
    "snowflake": validate_snowflake_tool_definition,
}


def validate_tools_configuration(
    raw_configuration: dict[str, Any],
) -> ToolsConfiguration:
    """Validate mixed tool definitions using their ``connector`` discriminator."""
    raw_tools = raw_configuration.get("tools")
    if not isinstance(raw_tools, list):
        raise ValueError("tool configuration must contain a 'tools' list")

    definitions: list[BaseToolDefinition] = []
    errors: list[str] = []

    for index, raw_tool in enumerate(raw_tools):
        if not isinstance(raw_tool, Mapping):
            errors.append(f"tools[{index}] must be a mapping")
            continue

        connector = str(raw_tool.get("connector") or "").strip().lower()
        if not connector:
            errors.append(f"tools[{index}] must declare a connector")
            continue

        validator = TOOL_DEFINITION_VALIDATORS.get(connector)
        if validator is None:
            supported = sorted(TOOL_DEFINITION_VALIDATORS)
            errors.append(
                f"tools[{index}] uses unsupported connector '{connector}'; "
                f"supported connectors: {supported}"
            )
            continue

        try:
            definitions.append(validator(raw_tool))
        except ValidationError as exc:
            errors.append(f"tools[{index}] is invalid for connector '{connector}': {exc}")

    if errors:
        raise ValueError("Invalid tool configuration:\n- " + "\n- ".join(errors))

    try:
        return ToolsConfiguration(tools=definitions)
    except ValidationError as exc:
        raise ValueError(f"Invalid tool configuration:\n{exc}") from exc


__all__ = ["TOOL_DEFINITION_VALIDATORS", "validate_tools_configuration"]
