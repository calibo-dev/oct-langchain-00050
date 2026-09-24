"""Load tool information from config/tools_info.yaml."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from latest_ai_development.connections.config import load_connection_connectors
from latest_ai_development.core.settings import CONFIG_DIR, load_yaml_file
from latest_ai_development.tools.schema import ToolsConfiguration
from latest_ai_development.tools.validator import validate_tools_configuration

TOOLS_INFO_CONFIG_PATH = CONFIG_DIR / "tools_info.yaml"


def load_tools_configuration(
    required_tool_names: Iterable[str] | None = None,
) -> ToolsConfiguration:
    """Load all tool definitions or only tools used by active agents."""
    raw_configuration = load_yaml_file(TOOLS_INFO_CONFIG_PATH)
    configured_tools = raw_configuration.get("tools")
    if not isinstance(configured_tools, list):
        raise ValueError("tools_info.yaml must contain a 'tools' list")

    connector_by_connection_name = load_connection_connectors()
    raw_tools = _add_resolved_connectors(
        configured_tools,
        connector_by_connection_name,
    )
    selected_configuration: dict[str, Any] = {"tools": raw_tools}

    if required_tool_names is not None:
        selected_configuration = _select_required_tools(
            selected_configuration,
            required_tool_names,
        )

    return validate_tools_configuration(selected_configuration)


def _add_resolved_connectors(
    configured_tools: list[Any],
    connector_by_connection_name: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Resolve each tool's connector through its configured connection name."""
    resolved_tools: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    errors: list[str] = []

    for index, raw_tool in enumerate(configured_tools):
        if not isinstance(raw_tool, Mapping):
            errors.append(f"tools[{index}] must be a mapping")
            continue
        if "connector" in raw_tool:
            errors.append(
                f"tools[{index}] must not declare connector; configure it in tools_connections.yaml"
            )
            continue

        tool_name = str(raw_tool.get("name") or "").strip()
        connection_name = str(raw_tool.get("connectionName") or "").strip()
        if tool_name and tool_name in seen_names:
            errors.append(f"duplicate tool name '{tool_name}'")
            continue
        if tool_name:
            seen_names.add(tool_name)

        connector = connector_by_connection_name.get(connection_name)
        if connector is None:
            errors.append(
                f"tool '{tool_name or index}' references unknown connection '{connection_name}'"
            )
            continue

        resolved_tool = dict(raw_tool)
        resolved_tool["connector"] = connector
        resolved_tools.append(resolved_tool)

    if errors:
        raise ValueError("Invalid tools_info.yaml configuration:\n- " + "\n- ".join(errors))

    return resolved_tools


def collect_connection_names(
    configuration: ToolsConfiguration,
) -> dict[str, tuple[str, ...]]:
    """Group reusable connection names by their resolved connector."""
    names_by_connector: dict[str, list[str]] = {}

    for definition in configuration.tools:
        connector_names = names_by_connector.setdefault(definition.connector, [])
        if definition.connection_name not in connector_names:
            connector_names.append(definition.connection_name)

    return {
        connector: tuple(connection_names)
        for connector, connection_names in names_by_connector.items()
    }


def tool_exists(configuration: ToolsConfiguration, tool_name: str) -> bool:
    """Return whether a tool exists in the loaded configuration."""
    return any(tool.name == tool_name for tool in configuration.tools)


def _select_required_tools(
    raw_configuration: dict[str, Any],
    required_tool_names: Iterable[str],
) -> dict[str, Any]:
    """Keep only tool records referenced by active agents."""
    raw_tools = raw_configuration.get("tools")
    if not isinstance(raw_tools, list):
        raise ValueError("tools_info.yaml must contain a 'tools' list")

    required_names = tuple(dict.fromkeys(required_tool_names))
    tools_by_name = {
        str(tool["name"]): tool
        for tool in raw_tools
        if isinstance(tool, Mapping) and "name" in tool
    }
    missing_names = [name for name in required_names if name not in tools_by_name]

    if missing_names:
        raise ValueError(
            f"Invalid tools_info.yaml configuration:\n- missing workflow tools: {missing_names}"
        )

    return {"tools": [tools_by_name[name] for name in required_names]}


__all__ = [
    "collect_connection_names",
    "load_tools_configuration",
    "tool_exists",
]
