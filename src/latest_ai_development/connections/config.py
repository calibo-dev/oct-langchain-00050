"""Load connector-specific connections from config/tools_connections.yaml."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from latest_ai_development.connections.schema import ConnectionConfigurations
from latest_ai_development.core.settings import CONFIG_DIR, load_yaml_file
from latest_ai_development.tools.discovery import get_connector

CONNECTIONS_CONFIG_PATH = CONFIG_DIR / "tools_connections.yaml"


def load_connection_connectors() -> dict[str, str]:
    """Return the connector assigned to every configured connection name.

    Tool entries contain only ``connectionName``. This lookup lets the tool
    loader determine which connector plugin must validate and build each tool.
    """
    raw_configuration = load_yaml_file(CONNECTIONS_CONFIG_PATH)
    connections_by_connector = _group_connections_by_connector(raw_configuration)

    connector_by_connection_name: dict[str, str] = {}
    for connector, connections in connections_by_connector.items():
        for connection in connections:
            connector_by_connection_name[str(connection["name"])] = connector

    return connector_by_connection_name


def load_connections_configuration(
    required_names_by_connector: Mapping[str, Iterable[str]] | None = None,
) -> ConnectionConfigurations:
    """Load and validate all connections, or only active tool connections."""
    raw_configuration = load_yaml_file(CONNECTIONS_CONFIG_PATH)
    connections_by_connector = _group_connections_by_connector(raw_configuration)
    connectors = (
        tuple(connections_by_connector)
        if required_names_by_connector is None
        else tuple(required_names_by_connector)
    )
    configurations: ConnectionConfigurations = {}

    for connector in connectors:
        plugin = get_connector(connector)
        connector_configuration = {
            "connections": connections_by_connector.get(connector, []),
        }

        if required_names_by_connector is not None:
            connector_configuration = _select_required_connections(
                raw_configuration=connector_configuration,
                required_names=required_names_by_connector[connector],
            )

        configurations[connector] = plugin.validate_connections(connector_configuration)

    return configurations


def _group_connections_by_connector(
    raw_configuration: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Validate common fields and group connection records by connector."""
    raw_connections = raw_configuration.get("connections")
    if not isinstance(raw_connections, list):
        raise ValueError("tools_connections.yaml must contain a 'connections' list")

    connections_by_connector: dict[str, list[dict[str, Any]]] = {}
    seen_names: set[str] = set()
    errors: list[str] = []

    for index, raw_connection in enumerate(raw_connections):
        if not isinstance(raw_connection, Mapping):
            errors.append(f"connections[{index}] must be a mapping")
            continue

        connection_name = str(raw_connection.get("name") or "").strip()
        connector = str(raw_connection.get("connector") or "").strip().lower()

        if not connection_name:
            errors.append(f"connections[{index}] must declare a name")
            continue
        if connection_name in seen_names:
            errors.append(f"duplicate connection name '{connection_name}'")
            continue
        seen_names.add(connection_name)

        if not connector:
            errors.append(f"connection '{connection_name}' must declare a connector")
            continue
        try:
            get_connector(connector)
        except ValueError as exc:
            errors.append(f"connection '{connection_name}' has an invalid connector: {exc}")
            continue

        connection = dict(raw_connection)
        connection["name"] = connection_name
        connection["connector"] = connector
        connections_by_connector.setdefault(connector, []).append(connection)

    if errors:
        raise ValueError("Invalid tools_connections.yaml configuration:\n- " + "\n- ".join(errors))

    return connections_by_connector


def _select_required_connections(
    raw_configuration: dict[str, Any],
    required_names: Iterable[str],
) -> dict[str, Any]:
    """Keep only connection records referenced by active tools."""
    raw_connections = raw_configuration.get("connections")
    if not isinstance(raw_connections, list):
        raise ValueError("tools_connections.yaml must contain a 'connections' list")

    ordered_names = tuple(dict.fromkeys(required_names))
    connections_by_name = {
        str(connection["name"]): connection
        for connection in raw_connections
        if isinstance(connection, Mapping) and "name" in connection
    }
    missing_names = [name for name in ordered_names if name not in connections_by_name]

    if missing_names:
        raise ValueError(
            "Invalid tools_connections.yaml configuration:\n- "
            f"missing tool connections: {missing_names}"
        )

    return {
        "connections": [connections_by_name[name] for name in ordered_names],
    }


__all__ = ["load_connection_connectors", "load_connections_configuration"]
