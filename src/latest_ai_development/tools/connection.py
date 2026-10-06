"""Resolve named connection configuration and own shared provider resources."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Lock
from typing import Any

import yaml
from dotenv import dotenv_values

from latest_ai_development.core.settings import BASE_DIR


def load_entries(path: Path, key: str) -> dict[str, dict[str, Any]]:
    """Read named YAML mappings, rejecting duplicate keys and invalid entries."""

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader: UniqueKeyLoader, node: Any) -> dict[str, Any]:
        result = {}
        for key_node, value_node in node.value:
            name = loader.construct_object(key_node)
            if not isinstance(name, str) or name in result:
                raise ValueError(f"{path.name} keys must be strings and unique")
            result[name] = loader.construct_object(value_node)
        return result

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    with path.open(encoding="utf-8") as file:
        document = yaml.load(file, Loader=UniqueKeyLoader)
    if not isinstance(document, dict) or set(document) != {key}:
        raise ValueError(f"{path.name} must contain only a '{key}' mapping")
    entries = document[key]
    if not isinstance(entries, dict):
        raise ValueError(f"{path.name} '{key}' must be a mapping")
    for name, entry in entries.items():
        if not name.strip() or name != name.strip() or not isinstance(entry, dict):
            raise ValueError(f"{path.name} entries must be named, trimmed mappings")
    return entries


def resolve_tool_config(
    tool_name: str,
    tool_config: Mapping[str, Any],
    connections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Join tools.yml with connection.yml without opening external connections."""
    resolved = dict(tool_config)
    if "connection_name" not in resolved:
        return resolved
    if "connector" in resolved or "configuration" in resolved:
        raise ValueError(f"Tool '{tool_name}' must put connector/configuration in connection.yml")
    name = resolved.get("connection_name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Tool '{tool_name}' requires connection_name")
    connection = connections.get(name)
    if connection is None:
        raise ValueError(f"Tool '{tool_name}' references undefined connection '{name}'")
    if set(connection) != {"connector", "configuration"}:
        raise ValueError(f"Connection '{name}' requires only connector and configuration")
    connector, configuration = connection["connector"], connection["configuration"]
    if not isinstance(connector, Mapping) or not isinstance(configuration, Mapping):
        raise ValueError(f"Connection '{name}' requires connector and configuration mappings")
    resolved["connector"] = dict(connector)
    resolved["configuration"] = dict(configuration)
    return resolved


class ConnectionManager:
    """One connection object per name within an application process."""

    def __init__(
        self,
        config_dir: Path,
        resolve_secret: Callable[[str], str | None] | None = None,
        env_file: Path = BASE_DIR / ".env",
    ) -> None:
        self.configurations = load_entries(config_dir / "connection.yml", "connections")
        self.resolve_secret = resolve_secret
        self._environment = dotenv_values(env_file)
        self._connections: dict[str, Any] = {}
        self._lock = Lock()

    def read_environment(self, variable_name: str) -> str:
        """Read the explicit YAML variable name; process values override .env."""
        return str(
            os.environ.get(variable_name, self._environment.get(variable_name)) or ""
        ).strip()

    def get_or_create[Connection](self, name: str, factory: Callable[[], Connection]) -> Connection:
        """Reuse a named connection, including when tools are created concurrently."""
        with self._lock:
            if name not in self._connections:
                connection = factory()
                if not callable(getattr(connection, "close", None)):
                    raise TypeError(f"Connection '{name}' must provide close()")
                self._connections[name] = connection
            return self._connections[name]

    def close(self) -> None:
        """Close each shared object once, attempting every close even after errors."""
        with self._lock:
            connections, self._connections = self._connections, {}
        errors = []
        for connection in {id(value): value for value in connections.values()}.values():
            try:
                connection.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("Tool connection cleanup failed", errors)
