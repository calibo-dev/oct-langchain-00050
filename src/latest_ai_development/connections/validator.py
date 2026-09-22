"""Delegate connection validation to discovered connector plugins."""

from typing import Any

from latest_ai_development.connections.schema import ConnectionConfiguration
from latest_ai_development.tools.discovery import get_connector


def validate_connections_configuration(
    connector: str, raw_configuration: dict[str, Any]
) -> ConnectionConfiguration:
    """Validate using the connector's own schema and error messages."""
    return get_connector(connector).validate_connections(raw_configuration)
