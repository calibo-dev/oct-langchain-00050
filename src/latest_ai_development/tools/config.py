"""Load and select tool configuration from connector YAML files."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from latest_ai_development.core.settings import CONFIG_DIR, load_yaml_file
from latest_ai_development.tools.discovery import discover_connectors
from latest_ai_development.tools.schema import ToolsConfiguration
from latest_ai_development.tools.validator import validate_tools_configuration

TOOLS_CONFIG_DIR = CONFIG_DIR / "tools"


def load_tools_configuration(
    required_tool_names: Iterable[str] | None = None,
) -> ToolsConfiguration:
    """Load all connector tools or only tools used by active agents."""
    raw_tools: list[Any] = []
    seen_names: set[str] = set()

    for connector in discover_connectors():
        config_path = TOOLS_CONFIG_DIR / f"{connector}_tools.yaml"
        raw_configuration = load_yaml_file(config_path)
        configured_tools = raw_configuration.get("tools")
        if not isinstance(configured_tools, list):
            raise ValueError(f"{config_path.name} must contain a 'tools' list")
        for tool in configured_tools:
            if not isinstance(tool, Mapping) or tool.get("connector") != connector:
                raise ValueError(
                    f"Every tool in {config_path.name} must use connector '{connector}'"
                )
            name = tool.get("name")
            if isinstance(name, str):
                if name in seen_names:
                    raise ValueError(f"Duplicate tool name '{name}' across tool configuration")
                seen_names.add(name)
        raw_tools.extend(configured_tools)

    raw_configuration = {"tools": raw_tools}
    if required_tool_names is not None:
        raw_configuration = _select_required_tools(
            raw_configuration,
            required_tool_names,
        )

    return validate_tools_configuration(raw_configuration)


def collect_connection_names(
    configuration: ToolsConfiguration,
) -> dict[str, tuple[str, ...]]:
    """Group reusable connection names by connector in first-use order."""
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
        raise ValueError("tool configuration must contain a 'tools' list")

    required_names = tuple(dict.fromkeys(required_tool_names))
    selected_tools: dict[str, dict[str, Any]] = {}
    duplicate_names: set[str] = set()

    for raw_tool in raw_tools:
        if not isinstance(raw_tool, Mapping):
            continue
        tool_name = raw_tool.get("name")
        if not isinstance(tool_name, str) or tool_name not in required_names:
            continue
        if tool_name in selected_tools:
            duplicate_names.add(tool_name)
        selected_tools[tool_name] = dict(raw_tool)

    missing_names = [name for name in required_names if name not in selected_tools]
    errors: list[str] = []
    if missing_names:
        errors.append(f"missing workflow tools in tool configuration: {missing_names}")
    if duplicate_names:
        errors.append(f"duplicate workflow tools in tool configuration: {sorted(duplicate_names)}")
    if errors:
        raise ValueError("Invalid tool configuration:\n- " + "\n- ".join(errors))

    return {"tools": [selected_tools[name] for name in required_names]}


__all__ = [
    "collect_connection_names",
    "load_tools_configuration",
    "tool_exists",
]
