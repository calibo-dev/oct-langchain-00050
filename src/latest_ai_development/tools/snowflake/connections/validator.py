"""Validate Snowflake connection configuration with Pydantic."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from latest_ai_development.tools.snowflake.connections.schema import (
    SnowflakeConnectionsConfiguration,
)


def validate_snowflake_connections_configuration(
    raw_configuration: dict[str, Any],
) -> SnowflakeConnectionsConfiguration:
    """Convert connection YAML into checked Snowflake connection objects."""
    try:
        return SnowflakeConnectionsConfiguration.model_validate(raw_configuration)
    except ValidationError as exc:
        raise ValueError(f"Invalid tools_connections.yaml configuration:\n{exc}") from exc
