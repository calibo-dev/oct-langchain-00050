"""Load YAML and create portable tools using the selected integration files."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ToolConfiguration(BaseModel):
    """Fields shared by tool integrations in tools_info.yaml."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    operation: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    connection_name: str = Field(alias="connectionName", min_length=1)
    display_name: str | None = Field(default=None, alias="displayName")
    description: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    usage_guidelines: list[str] = Field(default_factory=list, alias="usageGuidelines")
    non_usage_guidelines: list[str] = Field(default_factory=list, alias="nonUsageGuidelines")


@dataclass(frozen=True)
class ToolDefinition:
    """A callable and its schema before a framework wraps it as a native tool."""

    name: str
    description: str
    input_schema: type[BaseModel]
    execute: Callable[..., Any]
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    async_execute: Callable[..., Awaitable[Any]] | None = None
    uses_context: bool = False


@dataclass(frozen=True)
class ToolIntegration:
    """Configuration schema and factories exported by an integration file."""

    name: str
    operations: tuple[str, ...]
    connection_schema: type[BaseModel]
    create_connection: Callable[[BaseModel, Callable[[str], str | None] | None], Any]
    create_tool: Callable[[ToolConfiguration, Any], ToolDefinition]


def load_entries(path: Path, key: str) -> dict[str, dict[str, Any]]:
    """Read named YAML records, rejecting missing and duplicate names."""
    with path.open(encoding="utf-8") as file:
        document = yaml.safe_load(file)
    if not isinstance(document, dict) or not isinstance(document.get(key), list):
        raise ValueError(f"{path.name} must contain a '{key}' list")
    entries = {}
    for entry in document[key]:
        if not isinstance(entry, dict):
            raise ValueError(f"{path.name} entries must be mappings")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip() or name != name.strip() or name in entries:
            raise ValueError(f"{path.name} names must be nonempty, trimmed, and unique")
        entries[name] = entry
    return entries


def load_integration(name: str) -> ToolIntegration:
    """The connector name selects <name>_connection.py in this package."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(f"Invalid tool connector '{name}'")
    module_name = f"{__package__}.{name}_connection"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise ValueError(f"Missing integration file '{name}_connection.py'") from exc
        raise ValueError(f"Integration '{name}' is missing dependency '{exc.name}'") from exc
    integration = getattr(module, "integration", None)
    if not isinstance(integration, ToolIntegration) or integration.name != name:
        raise ValueError(f"Integration '{name}' must export a matching ToolIntegration")
    return integration


def build_tool_description(
    configuration: ToolConfiguration, context: Iterable[str] = ()
) -> str:
    """Combine configured guidance with optional integration-specific context."""
    lines = [configuration.description, "", f"Purpose: {configuration.purpose}", ""]
    lines.extend(context)
    if configuration.usage_guidelines:
        lines.extend(["", "Usage guidelines:"])
        lines.extend(f"- {value}" for value in configuration.usage_guidelines)
    if configuration.non_usage_guidelines:
        lines.extend(["", "Non-usage guidelines:"])
        lines.extend(f"- {value}" for value in configuration.non_usage_guidelines)
    return "\n".join(lines)


class ToolsManager:
    """Create selected tools and own the connections shared by those tools."""

    def __init__(
        self,
        config_dir: Path,
        resolve_secret: Callable[[str], str | None] | None = None,
    ) -> None:
        self._config_dir = config_dir
        self._resolve_secret = resolve_secret
        self._connections: dict[str, Any] = {}

    def create_tools(self, tool_names: Iterable[str] | None = None) -> list[ToolDefinition]:
        """Read configuration once at startup; an empty selection needs no files."""
        selected = None if tool_names is None else tuple(dict.fromkeys(tool_names))
        if selected == ():
            return []
        entries = load_entries(self._config_dir / "tools_info.yaml", "tools")
        selected = tuple(entries) if selected is None else selected
        missing = set(selected) - entries.keys()
        if missing:
            raise ValueError(f"Missing workflow tools: {sorted(missing)}")
        if not selected:
            return []
        connections = load_entries(self._config_dir / "tools_connections.yaml", "connections")
        tools = []
        try:
            for name in selected:
                configuration = ToolConfiguration.model_validate(entries[name])
                connection_name = configuration.connection_name
                if connection_name not in connections:
                    raise ValueError(f"Tool '{name}' references a missing connection")
                connection_record = connections[connection_name]
                connector = str(connection_record.get("connector") or "").strip().lower()
                integration = load_integration(connector)
                if configuration.operation not in integration.operations:
                    raise ValueError(
                        f"Integration '{connector}' does not support operation "
                        f"'{configuration.operation}'"
                    )
                if connection_name not in self._connections:
                    validated = integration.connection_schema.model_validate(
                        {**connection_record, "connector": connector}
                    )
                    connection = integration.create_connection(validated, self._resolve_secret)
                    if not callable(getattr(connection, "close", None)):
                        raise TypeError(
                            f"Integration '{connector}' must create a closable connection"
                        )
                    self._connections[connection_name] = connection
                tool = integration.create_tool(configuration, self._connections[connection_name])
                if not isinstance(tool, ToolDefinition) or tool.name != name:
                    raise ValueError(
                        f"Integration '{connector}' returned an invalid tool definition"
                    )
                if not callable(tool.execute) or not issubclass(tool.input_schema, BaseModel):
                    raise ValueError(f"Tool '{name}' requires a callable and an input schema")
                tools.append(tool)
        except Exception:
            self.close()
            raise
        return tools

    def close(self) -> None:
        """Close each shared connection once, attempting cleanup after any failure."""
        connections, self._connections = self._connections, {}
        errors = []
        for connection in connections.values():
            try:
                connection.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("Tool connection cleanup failed", errors)
