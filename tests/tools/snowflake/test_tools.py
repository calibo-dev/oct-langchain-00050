import json

from latest_ai_development.tools.snowflake.schema import SnowflakeToolDefinition
from latest_ai_development.tools.snowflake.tools import (
    _add_row_limit,
    _build_metadata_query,
    create_snowflake_tool,
)


def test_select_query_receives_default_limit() -> None:
    assert _add_row_limit("SELECT * FROM COUNTRY_DATA_DB.REFERENCE.COUNTRIES;", 100) == (
        "SELECT * FROM COUNTRY_DATA_DB.REFERENCE.COUNTRIES LIMIT 100"
    )


def test_existing_query_limit_is_preserved() -> None:
    query = "SELECT * FROM COUNTRY_DATA_DB.REFERENCE.COUNTRIES LIMIT 10"
    assert _add_row_limit(query, 100) == query


def test_metadata_query_uses_qualified_information_schema() -> None:
    query = _build_metadata_query(
        scope="columns",
        database="DEV_DB",
        schema="DEV_SCHEMA",
        table_name="AK_COUNTRY",
        search_term="country",
        row_limit=100,
    )

    assert "FROM DEV_DB.INFORMATION_SCHEMA.COLUMNS" in query
    assert "UPPER(TABLE_SCHEMA) = 'DEV_SCHEMA'" in query
    assert "UPPER(TABLE_NAME) = 'AK_COUNTRY'" in query
    assert query.endswith("LIMIT 100")


def test_dynamic_tool_discovers_metadata_when_query_is_empty() -> None:
    cursor = FakeCursor()
    manager = FakeConnectionManager(FakeConnection(cursor))
    tool = create_snowflake_tool(_tool_definition(), manager)

    result = json.loads(tool.invoke({}))

    assert "FROM DEV_DB.INFORMATION_SCHEMA.TABLES" in cursor.executed_query
    assert result["status"] == "success"
    assert result["metadata_scope"] == "tables"
    assert result["rows"] == [["AK_COUNTRY"]]


class FakeCursor:
    description = [("TABLE_NAME",)]
    rowcount = 1

    def __init__(self) -> None:
        self.executed_query = ""

    def execute(self, query: str) -> None:
        self.executed_query = query

    def fetchmany(self, _: int) -> list[tuple[str]]:
        return [("AK_COUNTRY",)]

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


class FakeConnectionDefinition:
    database = "DEV_DB"
    schema_name = "DEV_SCHEMA"


class FakeConnectionManager:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def get_connection(self, connection_name: str) -> FakeConnection:
        assert connection_name == "shared_connection"
        return self.connection

    def get_definition(self, connection_name: str) -> FakeConnectionDefinition:
        assert connection_name == "shared_connection"
        return FakeConnectionDefinition()


def _tool_definition() -> SnowflakeToolDefinition:
    return SnowflakeToolDefinition.model_validate(
        {
            "name": "country_data_tool",
            "connector": "snowflake",
            "connectionName": "shared_connection",
            "description": "Read country data.",
            "purpose": "Answer country-data questions.",
        }
    )
