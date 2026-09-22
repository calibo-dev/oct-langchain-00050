"""Construct configured tools through discovered connector plugins."""

from typing import Any

from latest_ai_development.connections.registry import ConnectionRegistry
from latest_ai_development.core.settings import Settings
from latest_ai_development.tools.discovery import get_connector
from latest_ai_development.tools.registry import ToolRegistry
from latest_ai_development.tools.schema import BaseToolDefinition, ToolsConfiguration


def build_tool_registry(
    settings: Settings,
    configuration: ToolsConfiguration,
    connection_registry: ConnectionRegistry,
) -> ToolRegistry:
    """Build active tools using the already-created connection managers."""
    return ToolRegistry(
        {
            definition.name: create_tool(settings, definition, connection_registry)
            for definition in configuration.tools
        }
    )


def create_tool(
    settings: Settings,
    definition: BaseToolDefinition,
    connection_registry: ConnectionRegistry,
) -> Any:
    """Select a connector by the validated tool definition's discriminator."""
    plugin = get_connector(definition.connector)
    manager = connection_registry.get(definition.connector)
    return plugin.build_tool(settings, definition, manager)
