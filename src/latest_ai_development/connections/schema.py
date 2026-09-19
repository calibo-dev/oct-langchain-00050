"""Connector-neutral connection configuration types."""

from __future__ import annotations

from latest_ai_development.connections.snowflake.schema import (
    SnowflakeConnectionsConfiguration,
)

type ConnectionConfiguration = SnowflakeConnectionsConfiguration
type ConnectionConfigurations = dict[str, ConnectionConfiguration]

__all__ = ["ConnectionConfiguration", "ConnectionConfigurations"]
