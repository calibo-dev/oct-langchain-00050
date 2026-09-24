"""Discover installed connector modules, never module paths supplied by YAML."""

import re
from collections.abc import Mapping
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from types import MappingProxyType

from latest_ai_development.tools.base import ConnectorPlugin

CONNECTOR_DIRECTORY = Path(__file__).resolve().parent / "connectors"
CONNECTOR_FILE_SUFFIX = "_connector.py"


@lru_cache(maxsize=1)
def discover_connectors() -> Mapping[str, ConnectorPlugin]:
    """Load connector modules once per process in deterministic order.

    Each ``*_connector.py`` module must export a matching ConnectorPlugin named
    ``plugin``. Restart the application after installing or changing a connector.
    """
    plugins: dict[str, ConnectorPlugin] = {}
    for connector_file in sorted(CONNECTOR_DIRECTORY.glob(f"*{CONNECTOR_FILE_SUFFIX}")):
        if not connector_file.is_file():
            continue
        module_name = connector_file.stem
        name = module_name.removesuffix("_connector")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError(f"Invalid connector module name: '{module_name}'")
        try:
            module = import_module(f"latest_ai_development.tools.connectors.{module_name}")
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
