"""Tests for generic database tools and dynamic connector discovery."""

from __future__ import annotations

import json
from typing import Any

from latest_ai_development.connections.base import MetadataScope
from latest_ai_development.connections.config import load_connections_configuration
from latest_ai_development.tools.config import (
    collect_connection_names,
    load_tools_configuration,
)
from latest_ai_development.tools.database_tools import (
    DatabaseToolDefinition,
    create_database_tool,
)
from latest_ai_development.tools.discovery import discover_connectors


class FakeDatabaseManager:
    """Small connector implementation used to verify generic delegation."""

    def get_connection_context(self, connection_name: str) -> dict[str, str]:
        assert connection_name == "test_connection"
        return {"Database": "TEST_DB"}

    def execute_query(
        self,
        connection_name: str,
        query: str,
        row_limit: int,
    ) -> dict[str, Any]:
        assert connection_name == "test_connection"
        assert query == "SELECT 1"
        return {
            "status": "success",
            "columns": ["VALUE"],
            "rows": [[1]],
            "row_count": 1,
            "row_limit": row_limit,
        }

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
        assert connection_name == "test_connection"
        return {
            "status": "success",
            "columns": ["NAME"],
            "rows": [["TABLE_A"]],
            "row_count": 1,
            "row_limit": row_limit,
            "metadata_scope": scope,
        }

    def close(self) -> None:
        """Satisfy the shared connection-manager lifecycle protocol."""


def test_configuration_resolves_dynamic_snowflake_connector() -> None:
    """Resolve tool configuration through the discovered connector module."""
    plugins = discover_connectors()
    tools = load_tools_configuration()
    connections = load_connections_configuration(collect_connection_names(tools))

    assert tuple(plugins) == ("snowflake",)
    assert type(tools.tools[0]).__name__ == "DatabaseToolDefinition"
    snowflake_connections = connections["snowflake"].model_dump()["connections"]
    assert snowflake_connections[0]["connector"] == "snowflake"


def test_database_tool_delegates_query_and_metadata_operations() -> None:
    """Keep query and metadata behavior independent of a concrete connector."""
    definition = DatabaseToolDefinition.model_validate(
        {
            "name": "database_tool",
            "connector": "testdb",
            "connectionName": "test_connection",
            "description": "Query test data.",
            "purpose": "Test generic database behavior.",
        }
    )
    tool = create_database_tool(definition, FakeDatabaseManager())
    assert tool.func is not None

    query_result = json.loads(tool.func(query="SELECT 1", row_limit=10))
    metadata_result = json.loads(tool.func(metadata_scope="tables", row_limit=10))

    assert query_result["rows"] == [[1]]
    assert metadata_result["metadata_scope"] == "tables"
