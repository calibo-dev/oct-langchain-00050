"""Dispatch connection validation to connector-specific validators."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from latest_ai_development.connections.schema import ConnectionConfiguration
from latest_ai_development.connections.snowflake.validator import (
    validate_snowflake_connections_configuration,
)

ConnectionValidator = Callable[[dict[str, Any]], ConnectionConfiguration]

CONNECTION_VALIDATORS: dict[str, ConnectionValidator] = {
    "snowflake": validate_snowflake_connections_configuration,
}


def validate_connections_configuration(
    connector: str,
    raw_configuration: dict[str, Any],
) -> ConnectionConfiguration:
    """Validate one connector's connection configuration."""
    validator = CONNECTION_VALIDATORS.get(connector)
    if validator is None:
        supported = sorted(CONNECTION_VALIDATORS)
        raise ValueError(
            f"Unsupported connection connector '{connector}'. Supported connectors: {supported}"
        )
    return validator(raw_configuration)


__all__ = ["CONNECTION_VALIDATORS", "validate_connections_configuration"]
