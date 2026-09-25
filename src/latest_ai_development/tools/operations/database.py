"""Framework-neutral database query and metadata operations."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...connections.manager import DatabaseConnectionManager, MetadataScope
from ..manager import ToolConfiguration, ToolDefinition, ToolOperation, ToolOperationError

logger = logging.getLogger(__name__)

DEFAULT_ROW_LIMIT = 1000
MAX_ROW_LIMIT = 5000


class DatabaseToolConfiguration(ToolConfiguration):
    """One database tool mapped to a connector-owned connection."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    connection_name: str = Field(alias="connectionName", min_length=1)


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
) -> DatabaseToolConfiguration:
    """Validate settings for a database operation."""
    return DatabaseToolConfiguration.model_validate(dict(raw_definition))


def create_database_tool(
    definition: DatabaseToolConfiguration,
    connection_manager: DatabaseConnectionManager,
) -> ToolDefinition:
    """Bind query and metadata operations to a compatible database manager."""
    if not isinstance(connection_manager, DatabaseConnectionManager):
        raise TypeError(f"Tool '{definition.name}' requires a database connection manager")

    def run_database_tool(
        query: str | None = None,
        row_limit: int = DEFAULT_ROW_LIMIT,
        metadata_scope: MetadataScope = "auto",
        database: str | None = None,
        schema_name: str | None = None,
        table_name: str | None = None,
        search_term: str | None = None,
    ) -> dict[str, Any]:
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
                "Database operation failed tool=%s connection=%s",
                definition.name,
                definition.connection_name,
            )
            raise ToolOperationError(operation) from exc

        return result

    return ToolDefinition(
        execute=run_database_tool,
        name=definition.name,
        description=_build_tool_description(definition, connection_manager),
        input_schema=DatabaseToolInput,
    )


def _build_tool_description(
    definition: DatabaseToolConfiguration,
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


operation = ToolOperation(
    name="database",
    validate_tool=validate_database_tool_definition,
    build_tool=create_database_tool,
)


__all__ = ["operation"]
