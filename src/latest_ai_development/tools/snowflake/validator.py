"""Validation entry points for Snowflake tool configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from latest_ai_development.tools.snowflake.schema import SnowflakeToolDefinition


def validate_snowflake_tool_definition(
    raw_definition: Mapping[str, Any],
) -> SnowflakeToolDefinition:
    """Validate one Snowflake tool selected by the generic dispatcher."""
    return SnowflakeToolDefinition.model_validate(dict(raw_definition))


__all__ = ["validate_snowflake_tool_definition"]
