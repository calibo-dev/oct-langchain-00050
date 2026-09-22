"""Register Snowflake through the shared connector discovery contract."""

from typing import Any

from pydantic import BaseModel

from latest_ai_development.connections.base import ConnectionManager
from latest_ai_development.core.settings import Settings
from latest_ai_development.tools.base import ConnectorPlugin
from latest_ai_development.tools.schema import BaseToolDefinition
from latest_ai_development.tools.snowflake.connections.connection import SnowflakeConnectionManager
from latest_ai_development.tools.snowflake.connections.schema import (
    SnowflakeConnectionsConfiguration,
)
from latest_ai_development.tools.snowflake.connections.validator import (
    validate_snowflake_connections_configuration,
)
from latest_ai_development.tools.snowflake.tools.schema import SnowflakeToolDefinition
from latest_ai_development.tools.snowflake.tools.tools import create_snowflake_tool
from latest_ai_development.tools.snowflake.tools.validator import validate_snowflake_tool_definition


def build_manager(configuration: BaseModel) -> SnowflakeConnectionManager:
    """Build one manager holding all active named Snowflake connections."""
    if not isinstance(configuration, SnowflakeConnectionsConfiguration):
        raise TypeError("Snowflake requires SnowflakeConnectionsConfiguration")
    return SnowflakeConnectionManager(configuration.connections)


def build_tool(
    settings: Settings,
    definition: BaseToolDefinition,
    manager: ConnectionManager,
) -> Any:
    """Bind a tool to the shared Snowflake manager without opening a connection."""
    if not isinstance(definition, SnowflakeToolDefinition):
        raise TypeError("Snowflake requires SnowflakeToolDefinition")
    if not isinstance(manager, SnowflakeConnectionManager):
        raise TypeError("Snowflake requires SnowflakeConnectionManager")
    return create_snowflake_tool(definition=definition, connection_manager=manager)


plugin = ConnectorPlugin(
    name="snowflake",
    validate_connections=validate_snowflake_connections_configuration,
    validate_tool=validate_snowflake_tool_definition,
    build_manager=build_manager,
    build_tool=build_tool,
)
