"""Connector-neutral LangChain tools for database queries and metadata."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from latest_ai_development.connections.base import DatabaseConnectionManager, MetadataScope
from latest_ai_development.core.errors import ToolExecutionError
from latest_ai_development.tools.schema import BaseToolDefinition

logger = logging.getLogger(__name__)

DEFAULT_ROW_LIMIT = 1000
MAX_ROW_LIMIT = 5000


class DatabaseToolDefinition(BaseToolDefinition):
    """One database tool mapped to a connector-owned connection."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DatabaseToolInput(BaseModel):
    """Arguments accepted by every connector-neutral database tool."""

    query: str | None = Field(
        default=None,
        description="Optional database query. Leave empty to discover authorized metadata.",
    )
    row_limit: int = Field(
        default=DEFAULT_ROW_LIMIT,
        ge=1,
        le=MAX_ROW_LIMIT,
        description="Maximum number of data or metadata rows to return.",
    )
    metadata_scope: MetadataScope = Field(
        default="auto",
        description="Metadata scope used when query is empty.",
    )
    database: str | None = Field(default=None, description="Database to inspect.")
    schema_name: str | None = Field(default=None, description="Schema to inspect.")
    table_name: str | None = Field(default=None, description="Table to inspect for columns.")
    search_term: str | None = Field(
        default=None,
        description="Case-insensitive text used to filter metadata names.",
    )


def validate_database_tool_definition(
    raw_definition: Mapping[str, Any],
) -> DatabaseToolDefinition:
    """Validate a database tool after its connector has been resolved."""
    return DatabaseToolDefinition.model_validate(dict(raw_definition))


def create_database_tool(
    definition: DatabaseToolDefinition,
    connection_manager: DatabaseConnectionManager,
) -> StructuredTool:
    """Create a LangChain tool backed by a connector-managed connection."""

    def run_database_tool(
        query: str | None = None,
        row_limit: int = DEFAULT_ROW_LIMIT,
        metadata_scope: MetadataScope = "auto",
        database: str | None = None,
        schema_name: str | None = None,
        table_name: str | None = None,
        search_term: str | None = None,
    ) -> str:
        """Execute a query or discover metadata through the selected connector."""
        normalized_query = str(query or "").strip()

        try:
            if normalized_query:
                result = connection_manager.execute_query(
                    definition.connection_name,
                    normalized_query,
                    row_limit,
                )
            else:
                result = connection_manager.discover_metadata(
                    connection_name=definition.connection_name,
                    scope=metadata_scope,
                    row_limit=row_limit,
                    database=database,
                    schema=schema_name,
                    table_name=table_name,
                    search_term=search_term,
                )
        except Exception as exc:
            operation = (
                "query_execution_failed" if normalized_query else "metadata_discovery_failed"
            )
            logger.exception(
                "Database operation failed tool=%s connector=%s",
                definition.name,
                definition.connector,
            )
            raise ToolExecutionError(definition.name, operation) from exc

        return json.dumps(result, default=str)

    return StructuredTool.from_function(
        func=run_database_tool,
        name=definition.name,
        description=_build_tool_description(definition, connection_manager),
        args_schema=DatabaseToolInput,
    )


def _build_tool_description(
    definition: DatabaseToolDefinition,
    connection_manager: DatabaseConnectionManager,
) -> str:
    """Build connector-neutral instructions shown to the LLM."""
    context = connection_manager.get_connection_context(definition.connection_name)
    lines = [
        definition.description.strip(),
        "",
        f"Purpose: {definition.purpose.strip()}",
        "",
        f"Connection: {definition.connection_name}",
        f"Connector: {definition.connector}",
    ]

    for label, value in context.items():
        if value:
            lines.append(f"{label}: {value}")

    lines.extend(
        [
            "",
            "Leave query empty to discover databases, schemas, tables, or columns.",
            "Prefer fully qualified object names in database queries.",
        ]
    )

    if definition.usage_guidelines:
        lines.extend(["", "Usage guidelines:"])
        lines.extend(f"- {guideline}" for guideline in definition.usage_guidelines)
    if definition.non_usage_guidelines:
        lines.extend(["", "Do not use this tool for:"])
        lines.extend(f"- {guideline}" for guideline in definition.non_usage_guidelines)
    return "\n".join(lines)


__all__ = [
    "DatabaseToolDefinition",
    "create_database_tool",
    "validate_database_tool_definition",
]
