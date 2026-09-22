"""Build shared connection managers through discovered connector plugins."""

from latest_ai_development.connections.registry import ConnectionRegistry
from latest_ai_development.connections.schema import ConnectionConfigurations
from latest_ai_development.tools.discovery import get_connector


def build_connection_registry(configurations: ConnectionConfigurations) -> ConnectionRegistry:
    """Build one manager per active connector, shared by its configured tools."""
    managers = {}
    for connector, configuration in configurations.items():
        managers[connector] = get_connector(connector).build_manager(configuration)
    return ConnectionRegistry(managers)
