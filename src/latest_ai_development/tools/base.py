"""Contract exported as ``plugin`` by each connector's plugin.py module."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from latest_ai_development.connections.base import ConnectionManager
from latest_ai_development.core.settings import Settings
from latest_ai_development.tools.schema import BaseToolDefinition


@dataclass(frozen=True)
class ConnectorPlugin:
    """Keep connector-specific validation and construction in its own package."""

    name: str
    validate_connections: Callable[[dict[str, Any]], BaseModel]
    validate_tool: Callable[[Mapping[str, Any]], BaseToolDefinition]
    build_manager: Callable[[BaseModel], ConnectionManager]
    build_tool: Callable[[Settings, BaseToolDefinition, ConnectionManager], Any]
