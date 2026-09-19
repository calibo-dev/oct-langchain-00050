"""Dispatch tool construction to connector-specific builders."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from latest_ai_development.connections.registry import ConnectionRegistry
from latest_ai_development.connections.snowflake.connection import (
    SnowflakeConnectionManager,
)
from latest_ai_development.core.settings import Settings
from latest_ai_development.tools.registry import ToolRegistry
from latest_ai_development.tools.schema import BaseToolDefinition, ToolsConfiguration
from latest_ai_development.tools.snowflake.schema import SnowflakeToolDefinition
from latest_ai_development.tools.snowflake.tools import create_snowflake_tool

ToolBuilder = Callable[[Settings, BaseToolDefinition, ConnectionRegistry], Any]


def _build_snowflake_tool(
    settings: Settings,
    definition: BaseToolDefinition,
    connection_registry: ConnectionRegistry,
) -> Any:
    """Build one Snowflake tool after connector dispatch."""
    del settings  # Reserved for connector builders that need application settings.

    if not isinstance(definition, SnowflakeToolDefinition):
        raise TypeError(
            f"Connector 'snowflake' requires SnowflakeToolDefinition, got "
            f"{type(definition).__name__}"
        )

    connection_manager = cast(
        SnowflakeConnectionManager,
        connection_registry.get("snowflake"),
    )
    return create_snowflake_tool(
        definition=definition,
        connection_manager=connection_manager,
    )


# Connector implementations register one builder here. Agents and workflow code
# remain unchanged when another connector such as Databricks or MCP is added.
TOOL_BUILDERS: dict[str, ToolBuilder] = {
    "snowflake": _build_snowflake_tool,
}


def build_tool_registry(
    settings: Settings,
    configuration: ToolsConfiguration,
    connection_registry: ConnectionRegistry,
) -> ToolRegistry:
    """Create configured runtime tools and return their read-only registry."""
    tools = {
        definition.name: create_tool(settings, definition, connection_registry)
        for definition in configuration.tools
    }
    return ToolRegistry(tools)


def create_tool(
    settings: Settings,
    definition: BaseToolDefinition,
    connection_registry: ConnectionRegistry,
) -> Any:
    """Create a runtime tool using its connector discriminator."""
    builder = TOOL_BUILDERS.get(definition.connector)
    if builder is None:
        supported = sorted(TOOL_BUILDERS)
        raise ValueError(
            f"Unsupported tool connector '{definition.connector}'. "
            f"Supported connectors: {supported}"
        )
    return builder(settings, definition, connection_registry)


__all__ = ["TOOL_BUILDERS", "build_tool_registry", "create_tool"]
