"""Framework-independent configuration, validation, tool construction, and lifecycle."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, Self, runtime_checkable

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SecretResolver = Callable[[str], str | None]
INTEGRATION_DIRECTORY = Path(__file__).resolve().parent


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
    """Validation and construction functions for one integration operation."""

    name: str
    validate_tool: Callable[[Mapping[str, Any]], ToolConfiguration]
    build_tool: Callable[[ToolConfiguration, Any], ToolDefinition]


@runtime_checkable
class ConnectionManager(Protocol):
    """Lifecycle interface implemented by a provider's client manager."""

    def close(self) -> None:
        """Release every cached client or connection."""
        ...


@dataclass(frozen=True)
class ToolIntegration:
    """Contract exported as ``integration`` by a <name>_connection.py module."""

    name: str
    operations: Mapping[str, ToolOperation]
    validate_connections: Callable[[dict[str, Any]], BaseModel]
    build_manager: Callable[[BaseModel, SecretResolver | None], ConnectionManager]


@dataclass(frozen=True)
class ProviderConfiguration:
    """Validated settings and the connection names belonging to one provider."""

    names: tuple[str, ...]
    configuration: BaseModel


type ConnectionConfigurations = dict[str, ProviderConfiguration]


def discover_integrations() -> tuple[str, ...]:
    """List supplied integration files without importing their optional SDKs."""
    return tuple(
        path.stem.removesuffix("_connection")
        for path in sorted(INTEGRATION_DIRECTORY.glob("*_connection.py"))
        if path.is_file()
        and re.fullmatch(r"[a-z][a-z0-9_]*", path.stem.removesuffix("_connection"))
    )


@cache
def get_integration(name: str) -> ToolIntegration:
    """Import only the selected integration from this package's supplied files."""
    if name not in discover_integrations():
        raise ValueError(
            f"Missing tool integration '{name}_connection.py'; available: {discover_integrations()}"
        )
    try:
        module = import_module(f"{__package__}.{name}_connection")
    except ImportError as exc:
        raise ValueError(
            f"Unable to load integration '{name}'; install its required dependencies: {exc}"
        ) from exc
    integration = getattr(module, "integration", None)
    if not isinstance(integration, ToolIntegration) or integration.name != name:
        raise ValueError(
            f"Integration '{name}' must export a matching ToolIntegration as 'integration'"
        )
    if (
        not isinstance(integration.operations, Mapping)
        or not callable(integration.validate_connections)
        or not callable(integration.build_manager)
    ):
        raise ValueError(f"Integration '{name}' has invalid validation or construction functions")
    return integration


def load_connections_configuration(
    path: Path,
    required_names: Iterable[str] | None = None,
) -> ConnectionConfigurations:
    """Validate selected connections without opening clients or resolving credentials."""
    selected_names = None if required_names is None else tuple(dict.fromkeys(required_names))
    if selected_names == ():
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"Missing connection configuration: {path}")
    with path.open(encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    if not isinstance(raw, dict) or not isinstance(raw.get("connections"), list):
        raise ValueError(f"{path.name} must contain a 'connections' list")

    records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(raw["connections"]):
        if not isinstance(record, dict):
            raise ValueError(f"connections[{index}] must be a mapping")
        name = str(record.get("name") or "").strip()
        if not name or name in records:
            raise ValueError(f"Connection name '{name}' must be nonempty and unique")
        records[name] = {**record, "name": name}
    selected_names = tuple(records) if selected_names is None else selected_names
    missing = set(selected_names) - records.keys()
    if missing:
        raise ValueError(f"Missing tool connections: {sorted(missing)}")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for name in selected_names:
        record = records[name]
        connector = str(record.get("connector") or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", connector):
            raise ValueError(f"Connection '{name}' must declare a valid connector")
        grouped.setdefault(connector, []).append({**record, "connector": connector})

    return {
        connector: ProviderConfiguration(
            names=tuple(record["name"] for record in connections),
            configuration=get_integration(connector).validate_connections(
                {"connections": connections}
            ),
        )
        for connector, connections in grouped.items()
    }


class ConnectionRegistry:
    """Resolve named connections to their shared provider managers."""

    def __init__(
        self,
        managers: Mapping[str, ConnectionManager],
        providers_by_connection: Mapping[str, str],
    ) -> None:
        self._managers = dict(managers)
        self._providers_by_connection = dict(providers_by_connection)

    def get(self, connection_name: str) -> ConnectionManager:
        """Return the manager responsible for a configured connection."""
        try:
            return self._managers[self._providers_by_connection[connection_name]]
        except KeyError as exc:
            raise KeyError(f"Connection '{connection_name}' is not available") from exc

    def close(self) -> None:
        """Attempt cleanup of every provider even if one provider fails."""
        errors: list[Exception] = []
        for manager in self._managers.values():
            try:
                manager.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("Connection cleanup failed", errors)


def build_connection_registry(
    configurations: ConnectionConfigurations,
    resolve_secret: SecretResolver | None = None,
) -> ConnectionRegistry:
    """Create one manager per selected provider; credentials remain lazy."""
    managers: dict[str, ConnectionManager] = {}
    providers_by_connection: dict[str, str] = {}
    try:
        for name, selected in configurations.items():
            manager = get_integration(name).build_manager(selected.configuration, resolve_secret)
            if not isinstance(manager, ConnectionManager):
                raise TypeError(f"Provider '{name}' must return a manager with close()")
            managers[name] = manager
            for connection_name in selected.names:
                providers_by_connection[connection_name] = name
    except Exception:
        ConnectionRegistry(managers, providers_by_connection).close()
        raise
    return ConnectionRegistry(managers, providers_by_connection)


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
        definition = ToolConfiguration.model_validate(record)
        definitions.append(definition)
    return ToolsConfiguration(tools=definitions)


def collect_connection_names(configuration: ToolsConfiguration) -> tuple[str, ...]:
    """Collect connections only for operations that declare a connection reference."""
    return tuple(
        dict.fromkeys(
            tool.connection_name for tool in configuration.tools if tool.connection_name is not None
        )
    )


@dataclass(frozen=True)
class ToolSetup:
    """Validated active tools, connections, and integration ownership."""

    tools: tuple[ToolConfiguration, ...]
    connections: ConnectionConfigurations
    integrations: Mapping[str, str]


def load_configuration(config_dir: Path, tool_names: Iterable[str]) -> ToolSetup:
    """Read both YAML files and validate only integrations used by active tools."""
    configuration = load_tools_configuration(config_dir / "tools_info.yaml", tool_names)
    connections = load_connections_configuration(
        config_dir / "tools_connections.yaml", collect_connection_names(configuration)
    )
    providers_by_connection = {
        name: connector
        for connector, selected in connections.items()
        for name in selected.names
    }
    definitions: list[ToolConfiguration] = []
    integrations: dict[str, str] = {}
    for definition in configuration.tools:
        # Connection-backed tools select their integration through the connection.
        # A connectionless integration uses its operation name as its module name.
        connector = (
            providers_by_connection[definition.connection_name]
            if definition.connection_name is not None
            else definition.operation
        )
        integration = get_integration(connector)
        operation = integration.operations.get(definition.operation)
        if not isinstance(operation, ToolOperation) or operation.name != definition.operation:
            raise ValueError(
                f"Integration '{connector}' does not support operation '{definition.operation}'"
            )
        if not callable(operation.validate_tool) or not callable(operation.build_tool):
            raise ValueError(
                f"Operation '{definition.operation}' has invalid construction functions"
            )
        validated = operation.validate_tool(definition.model_dump(by_alias=True))
        if (
            not isinstance(validated, ToolConfiguration)
            or validated.name != definition.name
            or validated.operation != definition.operation
            or validated.connection_name != definition.connection_name
        ):
            raise ValueError(f"Integration '{connector}' changed the configured tool identity")
        definitions.append(validated)
        integrations[definition.name] = connector
    return ToolSetup(tuple(definitions), connections, integrations)


class ToolsManager:
    """Own portable tools and their shared connection resources."""

    def __init__(
        self, tools: Mapping[str, ToolDefinition], connections: ConnectionRegistry
    ) -> None:
        self._tools = dict(tools)
        self._connections = connections

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

    def close(self) -> None:
        """Release the resources shared by these tools."""
        self._connections.close()


def _build_tool_definitions(
    configuration: ToolSetup,
    get_connection: Callable[[str], Any] | None = None,
) -> dict[str, ToolDefinition]:
    """Bind operations to connections without requiring a connection package for local tools."""
    tools: dict[str, ToolDefinition] = {}
    for definition in configuration.tools:
        connection = None
        if definition.connection_name is not None:
            if get_connection is None:
                raise ValueError(f"Tool '{definition.name}' requires a connection registry")
            connection = get_connection(definition.connection_name)
        integration = get_integration(configuration.integrations[definition.name])
        tool = integration.operations[definition.operation].build_tool(definition, connection)
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
    return tools


def build_tools_manager(
    configuration: ToolSetup,
    resolve_secret: SecretResolver | None = None,
) -> ToolsManager:
    """Create portable tools and retain ownership of their shared resources."""
    connections = build_connection_registry(configuration.connections, resolve_secret)
    try:
        tools = _build_tool_definitions(configuration, connections.get)
    except Exception:
        connections.close()
        raise
    return ToolsManager(tools, connections)
