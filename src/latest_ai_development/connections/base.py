"""Shared protocols implemented by connector-specific connection managers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol

MetadataScope = Literal["auto", "databases", "schemas", "tables", "columns"]


class ConnectionManager(Protocol):
    """Minimal lifecycle interface required by the connection registry."""

    def close(self) -> None:
        """Close every cached connection."""
        ...


class DatabaseConnectionManager(ConnectionManager, Protocol):
    """Operations required by the connector-neutral database tool."""

    def get_connection_context(self, connection_name: str) -> Mapping[str, str | None]:
        """Return non-secret details used to describe a configured connection."""
        ...

    def execute_query(
        self,
        connection_name: str,
        query: str,
        row_limit: int,
    ) -> dict[str, Any]:
        """Execute a database query and return a serializable result."""
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
        """Discover database metadata through the connector's SQL dialect."""
        ...
