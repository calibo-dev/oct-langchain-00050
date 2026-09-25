"""Framework-neutral connection contracts, configuration, discovery, and lifecycle."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import yaml
from pydantic import BaseModel

MetadataScope = Literal["auto", "databases", "schemas", "tables", "columns"]
SecretResolver = Callable[[str], str | None]
PROVIDER_DIRECTORY = Path(__file__).resolve().parent / "providers"


@runtime_checkable
class ConnectionManager(Protocol):
    """Lifecycle interface implemented by a provider's client manager."""

    def close(self) -> None:
        """Release every cached client or connection."""
        ...


@runtime_checkable
class DatabaseConnectionManager(ConnectionManager, Protocol):
    """Operations required by the shared database tool."""

    def get_connection_context(self, connection_name: str) -> Mapping[str, str | None]:
        """Return non-secret details for a tool description."""
        ...

    def execute_query(self, connection_name: str, query: str, row_limit: int) -> dict[str, Any]:
        """Execute a query and return serializable values."""
        ...

    def discover_metadata(
        self,
        connection_name: str,
        scope: MetadataScope,
        row_limit: int,
        database: str | None,
        schema: str | None,
        table_name: str | None,
        search_term: str | None,
    ) -> dict[str, Any]:
        """Discover metadata using the provider's dialect."""
        ...


@dataclass(frozen=True)
class ConnectionProvider:
    """Contract exported as ``provider`` by a providers/<name>.py module."""

    name: str
    validate_connections: Callable[[dict[str, Any]], BaseModel]
    build_manager: Callable[[BaseModel, SecretResolver | None], ConnectionManager]


@dataclass(frozen=True)
class ProviderConfiguration:
    """Validated settings and the connection names belonging to one provider."""

    names: tuple[str, ...]
    configuration: BaseModel


type ConnectionConfigurations = dict[str, ProviderConfiguration]


def discover_providers() -> tuple[str, ...]:
    """List installed providers without importing their optional SDKs."""
    return tuple(
        path.stem
        for path in sorted(PROVIDER_DIRECTORY.glob("*.py"))
        if path.is_file() and re.fullmatch(r"[a-z][a-z0-9_]*", path.stem)
    )


@cache
def get_provider(name: str) -> ConnectionProvider:
    """Import only the selected provider from this package's installed modules."""
    if name not in discover_providers():
        raise ValueError(f"Unknown connection provider '{name}'; available: {discover_providers()}")
    try:
        module = import_module(f"{__package__}.providers.{name}")
    except ImportError as exc:
        raise ValueError(
            f"Unable to load provider '{name}'; install its required dependencies: {exc}"
        ) from exc
    provider = getattr(module, "provider", None)
    if not isinstance(provider, ConnectionProvider) or provider.name != name:
        raise ValueError(
            f"Provider '{name}' must export a matching ConnectionProvider as 'provider'"
        )
    if not callable(provider.validate_connections) or not callable(provider.build_manager):
        raise ValueError(f"Provider '{name}' has invalid validation or construction functions")
    return provider


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
            configuration=get_provider(connector).validate_connections(
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
            manager = get_provider(name).build_manager(selected.configuration, resolve_secret)
            if not isinstance(manager, ConnectionManager):
                raise TypeError(f"Provider '{name}' must return a manager with close()")
            managers[name] = manager
            for connection_name in selected.names:
                providers_by_connection[connection_name] = name
    except Exception:
        ConnectionRegistry(managers, providers_by_connection).close()
        raise
    return ConnectionRegistry(managers, providers_by_connection)
