"""Create runtime connection managers from validated configuration."""

from __future__ import annotations

from collections.abc import Callable

from latest_ai_development.connections.base import ConnectionManager
from latest_ai_development.connections.registry import ConnectionRegistry
from latest_ai_development.connections.schema import (
    ConnectionConfiguration,
    ConnectionConfigurations,
)
from latest_ai_development.connections.snowflake.connection import (
    SnowflakeConnectionManager,
)
from latest_ai_development.connections.snowflake.schema import (
    SnowflakeConnectionsConfiguration,
)

ConnectionManagerBuilder = Callable[[ConnectionConfiguration], ConnectionManager]


def _build_snowflake_manager(
    configuration: ConnectionConfiguration,
) -> ConnectionManager:
    if not isinstance(configuration, SnowflakeConnectionsConfiguration):
        raise TypeError("Snowflake requires SnowflakeConnectionsConfiguration")
    return SnowflakeConnectionManager(configuration.connections)


CONNECTION_MANAGER_BUILDERS: dict[str, ConnectionManagerBuilder] = {
    "snowflake": _build_snowflake_manager,
}


def build_connection_registry(
    configurations: ConnectionConfigurations,
) -> ConnectionRegistry:
    """Create configured connection managers and return their registry."""
    managers: dict[str, ConnectionManager] = {}

    for connector, configuration in configurations.items():
        builder = CONNECTION_MANAGER_BUILDERS.get(connector)
        if builder is None:
            supported = sorted(CONNECTION_MANAGER_BUILDERS)
            raise ValueError(
                f"Unsupported connection connector '{connector}'. Supported connectors: {supported}"
            )
        managers[connector] = builder(configuration)

    return ConnectionRegistry(managers)


__all__ = ["CONNECTION_MANAGER_BUILDERS", "build_connection_registry"]
