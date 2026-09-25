"""Framework-neutral tool contracts, operation discovery, configuration, and registry."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import import_module
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OPERATION_DIRECTORY = Path(__file__).resolve().parent / "operations"


class ToolConfiguration(BaseModel):
    """Application-specific settings shared by all tool operations."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    operation: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    connection_name: str | None = Field(default=None, alias="connectionName", min_length=1)
    display_name: str | None = Field(default=None, alias="displayName")
    description: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    usage_guidelines: list[str] = Field(default_factory=list, alias="usageGuidelines")
    non_usage_guidelines: list[str] = Field(default_factory=list, alias="nonUsageGuidelines")

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        """Treat a blank optional display name as missing."""
        return None if value is None else str(value).strip() or None

    @field_validator("connection_name")
    @classmethod
    def validate_connection_name(cls, value: str | None) -> str | None:
        """Keep connection references consistent with connection registry keys."""
        if value is not None and not value.strip():
            raise ValueError("connectionName must not be blank")
        return value.strip() if value is not None else None

    @field_validator("tags", "usage_guidelines", "non_usage_guidelines")
    @classmethod
    def validate_text_values(cls, values: list[str]) -> list[str]:
        """Normalize description lists and reject empty or repeated entries."""
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("values must be nonempty and unique")
        return cleaned


class ToolsConfiguration(BaseModel):
    """Validated tool entries selected for the application."""

    model_config = ConfigDict(extra="forbid")
    tools: list[ToolConfiguration] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_names(self) -> Self:
        """Keep configured tool names unique across operations."""
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        return self


class ToolOperationError(RuntimeError):
    """Portable operation failure translated by the framework adapter."""


@dataclass(frozen=True)
class ToolDefinition:
    """A validated operation bound to its configured resources, before adaptation."""

    name: str
    description: str
    input_schema: type[BaseModel]
    execute: Callable[..., Any]
    async_execute: Callable[..., Awaitable[Any]] | None = None
    # The adapter supplies read-only invocation context, outside model arguments.
    uses_context: bool = False


@dataclass(frozen=True)
class ToolOperation:
    """Contract exported as ``operation`` by an operations/<name>.py module."""

    name: str
    validate_tool: Callable[[Mapping[str, Any]], ToolConfiguration]
    build_tool: Callable[[ToolConfiguration, Any], ToolDefinition]


def discover_operations() -> tuple[str, ...]:
    """List installed operation modules without importing unused integrations."""
    return tuple(
        path.stem
        for path in sorted(OPERATION_DIRECTORY.glob("*.py"))
        if path.is_file() and re.fullmatch(r"[a-z][a-z0-9_]*", path.stem)
    )


@cache
def get_operation(name: str) -> ToolOperation:
    """Load only the selected operation from installed package files."""
    if name not in discover_operations():
        raise ValueError(f"Unknown tool operation '{name}'; available: {discover_operations()}")
    try:
        module = import_module(f"{__package__}.operations.{name}")
    except ImportError as exc:
        raise ValueError(f"Unable to load tool operation '{name}': {exc}") from exc
    operation = getattr(module, "operation", None)
    if not isinstance(operation, ToolOperation) or operation.name != name:
        raise ValueError(f"Operation '{name}' must export a matching ToolOperation as 'operation'")
    if not callable(operation.validate_tool) or not callable(operation.build_tool):
        raise ValueError(f"Operation '{name}' has invalid validation or construction functions")
    return operation


def load_tools_configuration(
    path: Path,
    required_tool_names: Iterable[str] | None = None,
) -> ToolsConfiguration:
    """Read selected tools; an explicitly empty selection requires no YAML file."""
    selected = None if required_tool_names is None else tuple(dict.fromkeys(required_tool_names))
    if selected == ():
        return ToolsConfiguration()
    if not path.is_file():
        raise FileNotFoundError(f"Missing tool configuration: {path}")
    with path.open(encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    if not isinstance(raw, dict) or not isinstance(raw.get("tools"), list):
        raise ValueError(f"{path.name} must contain a 'tools' list")

    records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(raw["tools"]):
        if not isinstance(record, dict):
            raise ValueError(f"tools[{index}] must be a mapping")
        name = record.get("name")
        if not isinstance(name, str) or not name.strip() or name in records:
            raise ValueError(f"Tool name '{name}' must be nonempty and unique")
        records[name] = record
    selected = tuple(records) if selected is None else selected
    missing = set(selected) - records.keys()
    if missing:
        raise ValueError(f"Missing workflow tools: {sorted(missing)}")

    definitions: list[ToolConfiguration] = []
    for name in selected:
        record = records[name]
        operation_name = record.get("operation")
        if not isinstance(operation_name, str):
            raise ValueError(f"Tool '{name}' must declare an operation")
        definition = get_operation(operation_name).validate_tool(record)
        if not isinstance(definition, ToolConfiguration):
            raise TypeError(f"Operation '{operation_name}' must return ToolConfiguration")
        if definition.name != name or definition.operation != operation_name:
            raise ValueError(f"Operation '{operation_name}' changed the configured tool identity")
        definitions.append(definition)
    return ToolsConfiguration(tools=definitions)


def collect_connection_names(configuration: ToolsConfiguration) -> tuple[str, ...]:
    """Collect connections only for operations that declare a connection reference."""
    return tuple(
        dict.fromkeys(
            tool.connection_name for tool in configuration.tools if tool.connection_name is not None
        )
    )


class ToolRegistry:
    """Read-only lookup for framework-neutral tool definitions."""

    def __init__(self, tools: Mapping[str, ToolDefinition]) -> None:
        self._tools = dict(tools)

    def get(self, names: Iterable[str]) -> tuple[ToolDefinition, ...]:
        """Retrieve portable tools in the requested order."""
        try:
            return tuple(self._tools[name] for name in names)
        except KeyError as exc:
            raise KeyError(f"Tool '{exc.args[0]}' is not available") from exc

    def all(self) -> tuple[ToolDefinition, ...]:
        """Return the definitions to be converted by a framework adapter."""
        return tuple(self._tools.values())

    def count(self) -> int:
        """Return the number of registered tool definitions."""
        return len(self._tools)


def build_tool_registry(
    configuration: ToolsConfiguration,
    get_connection: Callable[[str], Any] | None = None,
) -> ToolRegistry:
    """Bind operations to connections without requiring a connection package for local tools."""
    tools: dict[str, ToolDefinition] = {}
    for definition in configuration.tools:
        connection = None
        if definition.connection_name is not None:
            if get_connection is None:
                raise ValueError(f"Tool '{definition.name}' requires a connection registry")
            connection = get_connection(definition.connection_name)
        tool = get_operation(definition.operation).build_tool(definition, connection)
        if not isinstance(tool, ToolDefinition) or tool.name != definition.name:
            raise ValueError(
                f"Operation '{definition.operation}' returned an invalid tool definition"
            )
        if not callable(tool.execute) or not issubclass(tool.input_schema, BaseModel):
            raise ValueError(f"Tool '{tool.name}' requires an input schema and execution callable")
        if tool.async_execute is not None and not callable(tool.async_execute):
            raise ValueError(f"Tool '{tool.name}' has an invalid asynchronous callable")
        if tool.uses_context and "context" in tool.input_schema.model_fields:
            raise ValueError(
                f"Tool '{tool.name}' cannot expose injected context as a model argument"
            )
        tools[tool.name] = tool
    return ToolRegistry(tools)
