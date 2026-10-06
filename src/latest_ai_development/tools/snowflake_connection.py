"""Snowflake configuration, connections, query execution, and metadata discovery."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping
from threading import Lock
from typing import Any, Literal, Self

import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from latest_ai_development.core.errors import ToolExecutionError

from .connection import ConnectionManager

logger = logging.getLogger(__name__)


class SnowflakeAuthentication(BaseModel):
    """Environment-variable names for the direct PAT or secret-name source."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    direct_pat_token: str = Field(alias="directPatToken", min_length=1)
    secret: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        if self.direct_pat_token == self.secret:
            raise ValueError("directPatToken and secret must reference different variables")
        return self


class SnowflakeConnectionOptions(BaseModel):
    """Connection options using the existing YAML field names."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    client_session_keep_alive: bool = Field(default=False, alias="clientSessionKeepAlive")
    login_timeout: int = Field(default=30, alias="loginTimeout", gt=0)
    network_timeout: int = Field(default=60, alias="networkTimeout", gt=0)


class SnowflakeConnectionConfiguration(BaseModel):
    """Non-secret settings for one named Snowflake connection."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    connector: Literal["snowflake"]
    account: str = Field(min_length=1)
    user: str = Field(min_length=1)
    warehouse: str = Field(min_length=1)
    host: str | None = None
    database: str | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    authentication: SnowflakeAuthentication
    connection_options: SnowflakeConnectionOptions = Field(
        default_factory=SnowflakeConnectionOptions, alias="connectionOptions"
    )

    @field_validator("host", "database", "schema_name", mode="before")
    @classmethod
    def normalize_optional_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None


class SnowflakeConnection:
    """Lazily open and reuse a client for one configured connection."""

    def __init__(
        self,
        configuration: SnowflakeConnectionConfiguration,
        resolve_secret: Callable[[str], str | None] | None = None,
        read_environment: Callable[[str], str] | None = None,
    ) -> None:
        self.configuration = configuration
        self._resolve_secret = resolve_secret
        self._read_environment = read_environment or (lambda name: os.getenv(name, "").strip())
        self._connection: Any = None
        self._lock = Lock()

    def _resolve_pat(self) -> str:
        authentication = self.configuration.authentication
        direct_pat = self._read_environment(authentication.direct_pat_token)
        secret_name = self._read_environment(authentication.secret)
        if bool(direct_pat) == bool(secret_name):
            raise RuntimeError(
                f"Connection '{self.configuration.name}' requires exactly one PAT source: "
                f"{authentication.direct_pat_token} or {authentication.secret}"
            )
        if direct_pat:
            return direct_pat
        if self._resolve_secret is None:
            raise RuntimeError("Snowflake secret authentication requires a secret resolver")
        token = str(self._resolve_secret(secret_name) or "").strip()
        if not token:
            raise RuntimeError(
                f"PAT secret for connection '{self.configuration.name}' resolved to an empty value"
            )
        return token

    def get_connection(self) -> Any:
        """Create a connection on first use, retaining it until closed."""
        with self._lock:
            if self._connection is not None and not self._connection.is_closed():
                return self._connection

            import snowflake.connector

            configuration = self.configuration
            parameters = {
                "account": configuration.account,
                "user": configuration.user,
                "warehouse": configuration.warehouse,
                "password": self._resolve_pat(),
                **configuration.connection_options.model_dump(),
            }
            for key, value in (
                ("host", configuration.host),
                ("database", configuration.database),
                ("schema", configuration.schema_name),
            ):
                if value:
                    parameters[key] = value
            try:
                self._connection = snowflake.connector.connect(**parameters)
            except snowflake.connector.errors.DatabaseError as exc:
                # Connector error details can include authentication values.
                raise RuntimeError(
                    f"Unable to open Snowflake connection '{configuration.name}'"
                ) from exc
            return self._connection

    def close(self) -> None:
        """Release this connection; repeated shutdown calls are harmless."""
        with self._lock:
            connection, self._connection = self._connection, None
            if connection is not None and not connection.is_closed():
                connection.close()


class SnowflakeToolInput(BaseModel):
    query: str | None = Field(
        default=None,
        description=(
            "Optional Snowflake SQL query. "
            "Leave empty to discover authorized Snowflake metadata before writing SQL."
        ),
    )
    row_limit: int | None = Field(
        default=1000,
        description=(
            "Maximum rows to return; defaults to 1000. Pass null for no tool-imposed limit."
        ),
    )
    metadata_scope: str | None = Field(
        default="auto",
        description=(
            "Metadata discovery scope when query is empty: auto, databases, schemas, "
            "tables, or columns."
        ),
    )
    database: str | None = Field(
        default=None,
        description="Optional Snowflake database name to inspect for schemas, tables, or columns.",
    )
    schema_name: str | None = Field(
        default=None,
        description="Optional Snowflake schema name to inspect for tables or columns.",
    )
    table_name: str | None = Field(
        default=None,
        description="Optional table name to inspect columns for.",
    )
    search_term: str | None = Field(
        default=None,
        description="Optional case-insensitive term used to filter discovered metadata names.",
    )


class SnowflakeTool:
    """Portable Snowflake query and metadata tool using configured settings."""

    args_schema: type[BaseModel] = SnowflakeToolInput

    def __init__(
        self, tool_name: str, tool_config: Mapping[str, Any], connection: SnowflakeConnection
    ) -> None:
        self.name = tool_name
        self.description = self._build_description(tool_config, connection)
        self._connection = connection

    @staticmethod
    def _build_description(tool_config: Mapping[str, Any], connection: SnowflakeConnection) -> str:
        details = connection.configuration
        lines = [
            tool_config.get("description") or "Query Snowflake data and discover metadata.",
            "",
            f"Purpose: {tool_config.get('purpose') or 'Read-only data retrieval.'}",
            "",
            "Leave query empty to discover metadata before writing SQL.",
            "Prefer fully qualified DATABASE.SCHEMA.TABLE names in SQL queries.",
            "",
            f"Connection: {details.name}",
        ]
        for label, value in (
            ("Account", details.account),
            ("Database", details.database),
            ("Schema", details.schema_name),
            ("Warehouse", details.warehouse),
        ):
            if value:
                lines.append(f"{label}: {value}")
        for key, label in (
            ("usage_guidelines", "Usage guidelines:"),
            ("non_usage_guidelines", "Non-usage guidelines:"),
        ):
            guidelines = tool_config.get(key, [])
            if not isinstance(guidelines, list) or any(
                not isinstance(value, str) for value in guidelines
            ):
                raise ValueError(f"{key} must be a list of strings")
            if guidelines:
                lines.extend(["", label, *(f"- {value}" for value in guidelines)])
        return "\n".join(lines)

    def close(self) -> None:
        """Release the shared connection when the application stops."""
        self._connection.close()

    def _run(
        self,
        query: str | None = None,
        row_limit: int | None = 1000,
        metadata_scope: str | None = "auto",
        database: str | None = None,
        schema_name: str | None = None,
        table_name: str | None = None,
        search_term: str | None = None,
    ) -> str:
        logger.debug(
            "Snowflake tool input | tool=%s | query=%s | row_limit=%s | metadata_scope=%s | "
            "database=%s | schema=%s | table_name=%s | search_term=%s",
            self.name,
            query or "",
            row_limit,
            metadata_scope,
            database or "",
            schema_name or "",
            table_name or "",
            search_term or "",
        )
        query = (query or "").strip()

        normalized_row_limit = self._normalize_row_limit(row_limit)

        if not query:
            return self._discover_metadata(
                row_limit=normalized_row_limit,
                metadata_scope=metadata_scope,
                database=database,
                schema=schema_name,
                table_name=table_name,
                search_term=search_term,
            )

        return self._execute_query(query=query, row_limit=normalized_row_limit)

    def _execute_query(self, query: str, row_limit: int | None) -> str:
        cursor = None

        try:
            self._validate_read_only_query(query)
            conn = self._connection.get_connection()
            cursor = conn.cursor()

            if row_limit is not None and self._should_apply_row_limit(query):
                query = f"{query.rstrip(';')} LIMIT {row_limit};"

            logger.debug(
                "Snowflake SQL query | tool=%s | query=%s",
                self.name,
                query,
            )
            cursor.execute(query)
            if cursor.description is None:
                affected = cursor.rowcount
                affected_text = (
                    str(affected) if affected is not None and affected >= 0 else "unknown"
                )
                result = f"Query executed successfully. Rows affected: {affected_text}."
                logger.debug(
                    "Snowflake tool data returned | tool=%s | data=%s",
                    self.name,
                    result,
                )
                return result

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            if not rows:
                result = "Query executed successfully - 0 rows returned."
                logger.debug(
                    "Snowflake tool data returned | tool=%s | data=%s",
                    self.name,
                    result,
                )
                return result

            df = pd.DataFrame(rows, columns=columns)
            result = (
                f"{len(rows)} row(s) returned:\n\n"
                f"{df.to_string(index=False)}\n\n"
                f"Columns: {', '.join(columns)}"
            )
            logger.debug(
                "Snowflake tool data returned | tool=%s | data=%s",
                self.name,
                result,
            )
            return result

        except Exception as exc:
            logger.exception(
                "Snowflake SQL execution failed | tool=%s | query=%s",
                self.name,
                query,
            )
            raise RuntimeError("query_execution_failed") from exc

        finally:
            if cursor is not None:
                cursor.close()

    def _discover_metadata(
        self,
        *,
        row_limit: int | None,
        metadata_scope: str | None,
        database: str | None,
        schema: str | None,
        table_name: str | None,
        search_term: str | None,
    ) -> str:
        cursor = None
        database = (database or self._connection.configuration.database or "").strip()
        schema = (schema or self._connection.configuration.schema_name or "").strip()
        table_name = (table_name or "").strip()
        search_term = (search_term or "").strip()
        scope = (metadata_scope or "auto").strip().lower()

        logger.debug(
            "Snowflake metadata input | tool=%s | scope=%s | database=%s | schema=%s | "
            "table_name=%s | search_term=%s | row_limit=%s",
            self.name,
            scope,
            database,
            schema,
            table_name,
            search_term,
            row_limit,
        )

        if scope == "auto":
            if table_name:
                scope = "columns"
            elif database and schema:
                scope = "tables"
            elif database:
                scope = "schemas"
            else:
                scope = "databases"

        try:
            conn = self._connection.get_connection()
            cursor = conn.cursor()

            if scope == "databases":
                sql = "SHOW DATABASES"
                logger.debug(
                    "Snowflake metadata query | tool=%s | scope=%s | sql=%s",
                    self.name,
                    scope,
                    sql,
                )
                cursor.execute(sql)
                return self._format_cursor_rows(
                    cursor,
                    row_limit=row_limit,
                    title="Authorized Snowflake databases",
                    search_term=search_term,
                )

            if scope == "schemas":
                if database:
                    sql = (
                        "SELECT CATALOG_NAME AS DATABASE_NAME, SCHEMA_NAME, COMMENT "
                        f"FROM {self._quote_identifier(database)}.INFORMATION_SCHEMA.SCHEMATA "
                    )
                    if search_term:
                        sql += (
                            f"WHERE UPPER(SCHEMA_NAME) LIKE {self._sql_like_literal(search_term)} "
                        )
                    sql += "ORDER BY SCHEMA_NAME"
                    if row_limit is not None:
                        sql += f" LIMIT {row_limit}"
                    logger.debug(
                        "Snowflake metadata query | tool=%s | scope=%s | sql=%s",
                        self.name,
                        scope,
                        sql,
                    )
                    cursor.execute(sql)
                    return self._format_cursor_rows(
                        cursor,
                        row_limit=row_limit,
                        title=f"Snowflake schemas in {database}",
                    )

                sql = "SHOW SCHEMAS IN ACCOUNT"
                logger.debug(
                    "Snowflake metadata query | tool=%s | scope=%s | sql=%s",
                    self.name,
                    scope,
                    sql,
                )
                cursor.execute(sql)
                return self._format_cursor_rows(
                    cursor,
                    row_limit=row_limit,
                    title="Authorized Snowflake schemas",
                    search_term=search_term,
                )

            if scope == "tables":
                if database:
                    sql = (
                        "SELECT TABLE_CATALOG AS DATABASE_NAME, TABLE_SCHEMA, TABLE_NAME, "
                        "TABLE_TYPE, COMMENT "
                        f"FROM {self._quote_identifier(database)}.INFORMATION_SCHEMA.TABLES "
                    )
                    filters = []
                    if schema:
                        filters.append(f"UPPER(TABLE_SCHEMA) = {self._sql_literal(schema.upper())}")
                    if search_term:
                        filters.append(
                            "(UPPER(TABLE_NAME) LIKE "
                            f"{self._sql_like_literal(search_term)} OR UPPER(COMMENT) LIKE "
                            f"{self._sql_like_literal(search_term)})"
                        )
                    if filters:
                        sql += "WHERE " + " AND ".join(filters) + " "
                    sql += "ORDER BY TABLE_SCHEMA, TABLE_NAME"
                    if row_limit is not None:
                        sql += f" LIMIT {row_limit}"
                    logger.debug(
                        "Snowflake metadata query | tool=%s | scope=%s | sql=%s",
                        self.name,
                        scope,
                        sql,
                    )
                    cursor.execute(sql)
                    return self._format_cursor_rows(
                        cursor,
                        row_limit=row_limit,
                        title=f"Snowflake tables in {database}{'.' + schema if schema else ''}",
                    )

                sql = "SHOW TABLES IN ACCOUNT"
                logger.debug(
                    "Snowflake metadata query | tool=%s | scope=%s | sql=%s",
                    self.name,
                    scope,
                    sql,
                )
                cursor.execute(sql)
                return self._format_cursor_rows(
                    cursor,
                    row_limit=row_limit,
                    title="Authorized Snowflake tables",
                    search_term=search_term,
                )

            if scope == "columns":
                if not database:
                    raise ValueError("Column discovery requires a database")

                sql = (
                    "SELECT TABLE_CATALOG AS DATABASE_NAME, TABLE_SCHEMA, TABLE_NAME, "
                    "COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COMMENT "
                    f"FROM {self._quote_identifier(database)}.INFORMATION_SCHEMA.COLUMNS "
                )
                filters = []
                if schema:
                    filters.append(f"UPPER(TABLE_SCHEMA) = {self._sql_literal(schema.upper())}")
                if table_name:
                    filters.append(f"UPPER(TABLE_NAME) = {self._sql_literal(table_name.upper())}")
                if search_term:
                    filters.append(
                        "(UPPER(TABLE_NAME) LIKE "
                        f"{self._sql_like_literal(search_term)} OR UPPER(COLUMN_NAME) LIKE "
                        f"{self._sql_like_literal(search_term)} OR UPPER(COMMENT) LIKE "
                        f"{self._sql_like_literal(search_term)})"
                    )
                if filters:
                    sql += "WHERE " + " AND ".join(filters) + " "
                sql += "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
                if row_limit is not None:
                    sql += f" LIMIT {row_limit}"
                logger.debug(
                    "Snowflake metadata query | tool=%s | scope=%s | sql=%s",
                    self.name,
                    scope,
                    sql,
                )
                cursor.execute(sql)
                return self._format_cursor_rows(
                    cursor,
                    row_limit=row_limit,
                    title=f"Snowflake columns in {database}",
                )

            raise ValueError(
                "metadata_scope must be one of auto, databases, schemas, tables, or columns"
            )

        except Exception as exc:
            logger.exception(
                "Snowflake metadata discovery failed | tool=%s | scope=%s",
                self.name,
                scope,
            )
            raise RuntimeError("metadata_discovery_failed") from exc

        finally:
            if cursor is not None:
                cursor.close()

    def _format_cursor_rows(
        self,
        cursor,
        *,
        row_limit: int | None,
        title: str,
        search_term: str = "",
    ) -> str:
        rows = cursor.fetchmany(row_limit) if row_limit is not None else cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        if search_term:
            term = search_term.lower()
            rows = [
                row
                for row in rows
                if term in " ".join("" if value is None else str(value) for value in row).lower()
            ]

        if not rows:
            result = f"{title}: 0 metadata row(s) found."
            logger.debug(
                "Snowflake metadata data returned | tool=%s | title=%s | data=%s",
                self.name,
                title,
                result,
            )
            return result

        df = pd.DataFrame(rows, columns=columns)
        result = (
            f"{title}: {len(rows)} metadata row(s) found:\n\n"
            f"{df.to_string(index=False)}\n\n"
            f"Columns: {', '.join(columns)}"
        )
        logger.debug(
            "Snowflake metadata data returned | tool=%s | title=%s | data=%s",
            self.name,
            title,
            result,
        )
        return result

    def _quote_identifier(self, identifier: str) -> str:
        parts = [part.strip() for part in str(identifier or "").split(".") if part.strip()]
        return ".".join(self._quote_identifier_part(part) for part in parts)

    def _quote_identifier_part(self, identifier: str) -> str:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            return identifier
        return f'"{identifier.replace(chr(34), chr(34) * 2)}"'

    def _sql_literal(self, value: str) -> str:
        return "'" + str(value or "").replace("'", "''") + "'"

    def _sql_like_literal(self, value: str) -> str:
        return self._sql_literal(f"%{str(value or '').upper()}%")

    def _normalize_row_limit(self, row_limit: int | None) -> int | None:
        if row_limit is None:
            return None
        try:
            return min(max(int(row_limit), 1), 5000)
        except TypeError, ValueError:
            return None

    def _should_apply_row_limit(self, query: str) -> bool:
        normalized = query.lstrip().upper()
        if not normalized.startswith(("SELECT", "WITH")):
            return False
        return re.search(r"\bLIMIT\s+\d+\b", normalized) is None

    def _validate_read_only_query(self, query: str) -> None:
        """Reject mutating or multi-statement SQL before it reaches Snowflake."""
        normalized = self._sql_without_comments_or_literals(query).strip()
        statement = normalized[:-1].rstrip() if normalized.endswith(";") else normalized

        if not statement:
            raise ValueError("A SQL query is required.")
        if ";" in statement:
            raise ValueError("Multiple SQL statements are not allowed.")
        if not re.match(r"^(SELECT|WITH|SHOW|DESCRIBE|DESC)\b", statement, re.IGNORECASE):
            raise ValueError("Only read-only SELECT, WITH, SHOW, or DESCRIBE queries are allowed.")

        forbidden = (
            r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|"
            r"CALL|COPY|PUT|GET|REMOVE|UNDROP|REPLACE)\b"
        )
        if re.search(forbidden, statement, re.IGNORECASE):
            raise ValueError("Mutating or administrative SQL is not allowed.")

    @staticmethod
    def _sql_without_comments_or_literals(query: str) -> str:
        value = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL)
        value = re.sub(r"--[^\n]*", " ", value)
        value = re.sub(r"'(?:''|[^'])*'", "''", value)
        return value


def create_tool(
    *, tool_name: str, tool_config: Mapping[str, Any], connection_manager: ConnectionManager
) -> StructuredTool:
    """Return a native LangChain tool directly from resolved YAML settings."""
    connector = tool_config["connector"]
    if connector != {"category": "RDBMS", "type": "SNOWFLAKE"}:
        raise ValueError(f"Tool '{tool_name}' requires an RDBMS/SNOWFLAKE connection")
    connection_name = tool_config["connection_name"]
    connection_settings = SnowflakeConnectionConfiguration.model_validate(
        {
            **tool_config["configuration"],
            "name": connection_name,
            "connector": "snowflake",
        }
    )
    connection = connection_manager.get_or_create(
        connection_name,
        lambda: SnowflakeConnection(
            connection_settings,
            connection_manager.resolve_secret,
            connection_manager.read_environment,
        ),
    )
    tool = SnowflakeTool(tool_name, tool_config, connection)

    def execute(**arguments: Any) -> str:
        try:
            return tool._run(**arguments)
        except Exception as exc:
            raise ToolExecutionError(tool_name, str(exc)) from exc

    return StructuredTool.from_function(
        func=execute,
        name=tool_name,
        description=tool.description,
        args_schema=SnowflakeToolInput,
        tags=tool_config.get("tags", []),
        metadata={
            "display_name": tool_config.get("display_name"),
            "connection_name": connection_name,
            "connector": "snowflake",
        },
    )
