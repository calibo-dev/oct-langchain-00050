"""Validate, build, and execute dynamic Snowflake tools."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from latest_ai_development.tools.schema import BaseToolDefinition
from latest_ai_development.tools.snowflake.connections import SnowflakeConnectionManager

logger = logging.getLogger(__name__)

DEFAULT_ROW_LIMIT = 1000
MAX_ROW_LIMIT = 5000
MetadataScope = Literal["auto", "databases", "schemas", "tables", "columns"]


class SnowflakeToolDefinition(BaseToolDefinition):
    """One Snowflake tool mapped to a reusable connection by name."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    connector: Literal["snowflake"]


def validate_snowflake_tool_definition(
    raw_definition: Mapping[str, Any],
) -> SnowflakeToolDefinition:
    """Validate one Snowflake tool selected by the generic dispatcher."""
    return SnowflakeToolDefinition.model_validate(dict(raw_definition))


class SnowflakeToolInput(BaseModel):
    """Arguments shared by every dynamically configured Snowflake tool."""

    query: str | None = Field(
        default=None,
        description=("Optional Snowflake SQL query. Leave empty to discover authorized metadata."),
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


def create_snowflake_tool(
    definition: SnowflakeToolDefinition,
    connection_manager: SnowflakeConnectionManager,
) -> StructuredTool:
    """Create a LangChain tool backed by a named reusable connection."""

    def run_snowflake_tool(
        query: str | None = None,
        row_limit: int = DEFAULT_ROW_LIMIT,
        metadata_scope: MetadataScope = "auto",
        database: str | None = None,
        schema_name: str | None = None,
        table_name: str | None = None,
        search_term: str | None = None,
    ) -> str:
        """Discover Snowflake metadata or execute the supplied SQL query."""
        connection = connection_manager.get_connection(definition.connection_name)
        normalized_query = str(query or "").strip()

        if normalized_query:
            return _execute_query(connection, normalized_query, row_limit, definition.name)

        connection_definition = connection_manager.get_definition(definition.connection_name)
        return _discover_metadata(
            connection=connection,
            connection_database=connection_definition.database,
            connection_schema=connection_definition.schema_name,
            scope=metadata_scope,
            row_limit=row_limit,
            database=database,
            schema=schema_name,
            table_name=table_name,
            search_term=search_term,
            tool_name=definition.name,
        )

    return StructuredTool.from_function(
        func=run_snowflake_tool,
        name=definition.name,
        description=_build_tool_description(definition, connection_manager),
        args_schema=SnowflakeToolInput,
    )


def _build_tool_description(
    definition: SnowflakeToolDefinition,
    connection_manager: SnowflakeConnectionManager,
) -> str:
    """Build the instructions the LLM sees when deciding whether to use a tool."""
    connection = connection_manager.get_definition(definition.connection_name)
    lines = [
        definition.description.strip(),
        "",
        f"Purpose: {definition.purpose.strip()}",
        "",
        f"Connection: {definition.connection_name}",
        f"Database: {connection.database}",
        f"Schema: {connection.schema_name}",
        "",
        "Leave query empty to discover databases, schemas, tables, or columns.",
        "Prefer fully qualified object names in SQL queries.",
    ]

    if definition.usage_guidelines:
        lines.extend(["", "Usage guidelines:"])
        lines.extend(f"- {guideline}" for guideline in definition.usage_guidelines)
    if definition.non_usage_guidelines:
        lines.extend(["", "Do not use this tool for:"])
        lines.extend(f"- {guideline}" for guideline in definition.non_usage_guidelines)
    return "\n".join(lines)


def _execute_query(connection: Any, query: str, row_limit: int, tool_name: str) -> str:
    """Execute SQL and return a predictable JSON result for the calling agent."""
    limited_query = _add_row_limit(query, row_limit)
    logger.debug("Executing Snowflake SQL tool=%s query=%s", tool_name, limited_query)

    cursor = connection.cursor()
    try:
        cursor.execute(limited_query)
        if cursor.description is None:
            return json.dumps(
                {
                    "status": "success",
                    "rows_affected": cursor.rowcount,
                }
            )
        return _serialize_cursor_rows(cursor, row_limit)
    except Exception as exc:
        logger.exception("Snowflake SQL execution failed tool=%s", tool_name)
        return _error_result("query_execution_failed", exc)
    finally:
        cursor.close()


def _discover_metadata(
    *,
    connection: Any,
    connection_database: str,
    connection_schema: str,
    scope: MetadataScope,
    row_limit: int,
    database: str | None,
    schema: str | None,
    table_name: str | None,
    search_term: str | None,
    tool_name: str,
) -> str:
    """Discover objects visible through the configured Snowflake connection."""
    selected_database = str(database or connection_database).strip()
    selected_schema = str(schema or connection_schema).strip()
    selected_table = str(table_name or "").strip()
    selected_search_term = str(search_term or "").strip()
    selected_scope = _resolve_metadata_scope(
        scope,
        selected_database,
        selected_schema,
        selected_table,
    )

    try:
        query = _build_metadata_query(
            scope=selected_scope,
            database=selected_database,
            schema=selected_schema,
            table_name=selected_table,
            search_term=selected_search_term,
            row_limit=row_limit,
        )
    except ValueError as exc:
        return _error_result("invalid_metadata_request", exc)

    logger.debug(
        "Discovering Snowflake metadata tool=%s scope=%s query=%s",
        tool_name,
        selected_scope,
        query,
    )
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        return _serialize_cursor_rows(cursor, row_limit, metadata_scope=selected_scope)
    except Exception as exc:
        logger.exception("Snowflake metadata discovery failed tool=%s", tool_name)
        return _error_result("metadata_discovery_failed", exc)
    finally:
        cursor.close()


def _resolve_metadata_scope(
    scope: MetadataScope,
    database: str,
    schema: str,
    table_name: str,
) -> MetadataScope:
    """Choose the most useful discovery level when the caller requests auto."""
    if scope != "auto":
        return scope
    if table_name:
        return "columns"
    if database and schema:
        return "tables"
    if database:
        return "schemas"
    return "databases"


def _build_metadata_query(
    *,
    scope: MetadataScope,
    database: str,
    schema: str,
    table_name: str,
    search_term: str,
    row_limit: int,
) -> str:
    """Build a metadata query from validated identifiers and escaped literals."""
    if scope == "databases":
        return "SHOW DATABASES"

    if not database:
        raise ValueError(f"metadata scope '{scope}' requires a database")

    quoted_database = _quote_identifier(database)
    if scope == "schemas":
        query = (
            "SELECT CATALOG_NAME AS DATABASE_NAME, SCHEMA_NAME, COMMENT "
            f"FROM {quoted_database}.INFORMATION_SCHEMA.SCHEMATA"
        )
        filters = _metadata_search_filters(search_term, ("SCHEMA_NAME", "COMMENT"))
        return _finish_metadata_query(query, filters, "SCHEMA_NAME", row_limit)

    if scope == "tables":
        query = (
            "SELECT TABLE_CATALOG AS DATABASE_NAME, TABLE_SCHEMA, TABLE_NAME, "
            f"TABLE_TYPE, COMMENT FROM {quoted_database}.INFORMATION_SCHEMA.TABLES"
        )
        filters = []
        if schema:
            filters.append(f"UPPER(TABLE_SCHEMA) = {_sql_literal(schema.upper())}")
        filters.extend(_metadata_search_filters(search_term, ("TABLE_NAME", "COMMENT")))
        return _finish_metadata_query(query, filters, "TABLE_SCHEMA, TABLE_NAME", row_limit)

    if scope == "columns":
        query = (
            "SELECT TABLE_CATALOG AS DATABASE_NAME, TABLE_SCHEMA, TABLE_NAME, "
            "COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COMMENT "
            f"FROM {quoted_database}.INFORMATION_SCHEMA.COLUMNS"
        )
        filters = []
        if schema:
            filters.append(f"UPPER(TABLE_SCHEMA) = {_sql_literal(schema.upper())}")
        if table_name:
            filters.append(f"UPPER(TABLE_NAME) = {_sql_literal(table_name.upper())}")
        filters.extend(
            _metadata_search_filters(search_term, ("TABLE_NAME", "COLUMN_NAME", "COMMENT"))
        )
        return _finish_metadata_query(
            query,
            filters,
            "TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION",
            row_limit,
        )

    raise ValueError(f"unsupported metadata scope '{scope}'")


def _metadata_search_filters(search_term: str, columns: tuple[str, ...]) -> list[str]:
    """Create one safe case-insensitive search expression for metadata columns."""
    if not search_term:
        return []
    pattern = _sql_literal(f"%{search_term.upper()}%")
    comparisons = [f"UPPER(COALESCE({column}, '')) LIKE {pattern}" for column in columns]
    return ["(" + " OR ".join(comparisons) + ")"]


def _finish_metadata_query(
    query: str,
    filters: list[str],
    order_by: str,
    row_limit: int,
) -> str:
    """Add optional filters, deterministic ordering, and a bounded row limit."""
    if filters:
        query += " WHERE " + " AND ".join(filters)
    return f"{query} ORDER BY {order_by} LIMIT {row_limit}"


def _add_row_limit(query: str, row_limit: int) -> str:
    """Apply a limit to SELECT/WITH queries that do not already specify one."""
    normalized_query = query.strip().rstrip(";")
    if normalized_query.upper().startswith(("SELECT", "WITH")) and not re.search(
        r"\bLIMIT\s+\d+\b",
        normalized_query,
        flags=re.IGNORECASE,
    ):
        normalized_query += f" LIMIT {row_limit}"
    return normalized_query


def _serialize_cursor_rows(
    cursor: Any,
    row_limit: int,
    metadata_scope: str | None = None,
) -> str:
    """Convert cursor rows to JSON without requiring a dataframe dependency."""
    columns = [column[0] for column in cursor.description or []]
    rows = cursor.fetchmany(row_limit)
    payload: dict[str, Any] = {
        "status": "success",
        "columns": columns,
        "rows": [list(row) for row in rows],
        "row_count": len(rows),
        "row_limit": row_limit,
    }
    if metadata_scope:
        payload["metadata_scope"] = metadata_scope
    return json.dumps(payload, default=str)


def _quote_identifier(identifier: str) -> str:
    """Quote a Snowflake identifier when it is not a simple safe name."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", identifier):
        return identifier
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _sql_literal(value: str) -> str:
    """Escape a string used as a Snowflake SQL literal."""
    return "'" + value.replace("'", "''") + "'"


def _error_result(error: str, exception: Exception) -> str:
    """Return an error to the agent in the same JSON transport used for data."""
    return json.dumps(
        {
            "status": "error",
            "error": error,
            "message": f"{type(exception).__name__}: {exception}",
        }
    )
