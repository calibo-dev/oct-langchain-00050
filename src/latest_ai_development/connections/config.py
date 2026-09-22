"""Load connection configuration from connector YAML files."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from latest_ai_development.connections.schema import ConnectionConfigurations
from latest_ai_development.connections.validator import (
    validate_connections_configuration,
)
from latest_ai_development.core.settings import CONFIG_DIR, load_yaml_file
from latest_ai_development.tools.discovery import discover_connectors, get_connector

TOOLS_CONFIG_DIR = CONFIG_DIR / "tools"


def load_connections_configuration(
    required_names_by_connector: Mapping[str, Iterable[str]] | None = None,
) -> ConnectionConfigurations:
    """Load connection definitions required by the active tools."""
    connectors = (
        tuple(discover_connectors())
        if required_names_by_connector is None
        else tuple(required_names_by_connector)
    )
    configurations: ConnectionConfigurations = {}

    for connector in connectors:
        config_path = _get_connection_config_path(connector)
        raw_configuration = load_yaml_file(config_path)

        if required_names_by_connector is not None:
            raw_configuration = _select_required_connections(
                raw_configuration=raw_configuration,
                required_names=required_names_by_connector[connector],
                config_path=config_path,
            )

        configurations[connector] = validate_connections_configuration(
            connector,
            raw_configuration,
        )

    return configurations


def _get_connection_config_path(connector: str) -> Path:
    """Return the configured YAML path for one connector."""
    get_connector(connector)
    return TOOLS_CONFIG_DIR / f"{connector}_connections.yaml"


def _select_required_connections(
    raw_configuration: dict[str, Any],
    required_names: Iterable[str],
    config_path: Path,
) -> dict[str, Any]:
    """Keep only connection records referenced by active tools."""
    raw_connections = raw_configuration.get("connections")
    if not isinstance(raw_connections, list):
        raise ValueError(f"{config_path.name} must contain a 'connections' list")

    ordered_names = tuple(dict.fromkeys(required_names))
    selected_connections: dict[str, dict[str, Any]] = {}
    duplicate_names: set[str] = set()

    for raw_connection in raw_connections:
        if not isinstance(raw_connection, Mapping):
            continue
        connection_name = raw_connection.get("name")
        if not isinstance(connection_name, str) or connection_name not in ordered_names:
            continue
        if connection_name in selected_connections:
            duplicate_names.add(connection_name)
        selected_connections[connection_name] = dict(raw_connection)

    missing_names = [name for name in ordered_names if name not in selected_connections]
    errors: list[str] = []
    if missing_names:
        errors.append(f"missing tool connections in {config_path.name}: {missing_names}")
    if duplicate_names:
        errors.append(
            f"duplicate tool connections in {config_path.name}: {sorted(duplicate_names)}"
        )
    if errors:
        raise ValueError(f"Invalid {config_path.name} configuration:\n- " + "\n- ".join(errors))

    return {
        "connections": [selected_connections[name] for name in ordered_names],
    }


__all__ = ["load_connections_configuration"]
