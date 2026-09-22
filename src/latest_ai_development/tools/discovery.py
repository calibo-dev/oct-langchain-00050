"""Discover installed connector packages, never module paths supplied by YAML."""

import re
from collections.abc import Mapping
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from types import MappingProxyType

from latest_ai_development.tools.base import ConnectorPlugin

CONNECTOR_DIRECTORY = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def discover_connectors() -> Mapping[str, ConnectorPlugin]:
    """Load immediate connector folders once per process in deterministic order.

    Each folder must contain plugin.py exporting a ConnectorPlugin named plugin.
    Restart the application after installing or changing a connector.
    """
    plugins: dict[str, ConnectorPlugin] = {}
    for directory in sorted(CONNECTOR_DIRECTORY.iterdir()):
        if not directory.is_dir() or not (directory / "plugin.py").is_file():
            continue
        name = directory.name
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError(f"Invalid connector folder name: '{name}'")
        try:
            module = import_module(f"latest_ai_development.tools.{name}.plugin")
        except Exception as exc:
            raise RuntimeError(f"Unable to load connector '{name}': {exc}") from exc
        plugin = getattr(module, "plugin", None)
        if not isinstance(plugin, ConnectorPlugin) or plugin.name != name:
            raise ValueError(
                f"Connector '{name}' must export a matching ConnectorPlugin as 'plugin'"
            )
        for operation in ("validate_connections", "validate_tool", "build_manager", "build_tool"):
            if not callable(getattr(plugin, operation)):
                raise ValueError(f"Connector '{name}' has invalid operation '{operation}'")
        if plugin.name in plugins:
            raise ValueError(f"Duplicate connector '{plugin.name}'")
        plugins[name] = plugin
    return MappingProxyType(plugins)


def get_connector(name: str) -> ConnectorPlugin:
    """Resolve a connector or report installed names in a clear startup error."""
    plugins = discover_connectors()
    try:
        return plugins[name]
    except KeyError as exc:
        raise ValueError(f"Unknown connector '{name}'; available: {sorted(plugins)}") from exc
