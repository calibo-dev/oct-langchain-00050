from typing import Any

import pytest

import latest_ai_development.connections.snowflake.connection as connection_module
from latest_ai_development.connections.snowflake.connection import (
    SnowflakeConnectionManager,
)
from latest_ai_development.connections.snowflake.schema import (
    SnowflakeConnectionDefinition,
)


def test_direct_pat_is_read_from_its_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _connection_definition()
    monkeypatch.setenv("SNOWFLAKE_TEST_PAT_TOKEN", "direct-pat")
    monkeypatch.delenv("SNOWFLAKE_TEST_PAT_SECRET_NAME", raising=False)

    parameters = SnowflakeConnectionManager._build_connection_parameters(definition)

    assert parameters["token"] == "direct-pat"
    assert parameters["authenticator"] == "programmatic_access_token"
    assert parameters["client_session_keep_alive"] is True
    assert parameters["login_timeout"] == 30
    assert parameters["network_timeout"] == 60


def test_pat_can_be_resolved_from_secret_manager_name_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_secret_names: list[str] = []

    class FakeSecretsManager:
        def get_secret(self, secret_name: str) -> str:
            resolved_secret_names.append(secret_name)
            return "secret-manager-pat"

    definition = _connection_definition()
    monkeypatch.delenv("SNOWFLAKE_TEST_PAT_TOKEN", raising=False)
    monkeypatch.setenv("SNOWFLAKE_TEST_PAT_SECRET_NAME", "snowflake-test-pat")
    monkeypatch.setattr(connection_module, "SecretsManager", FakeSecretsManager)

    parameters = SnowflakeConnectionManager._build_connection_parameters(definition)

    assert parameters["token"] == "secret-manager-pat"
    assert resolved_secret_names == ["snowflake-test-pat"]


def test_connection_rejects_both_pat_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNOWFLAKE_TEST_PAT_TOKEN", "direct-pat")
    monkeypatch.setenv("SNOWFLAKE_TEST_PAT_SECRET_NAME", "snowflake-test-pat")

    with pytest.raises(RuntimeError, match="both PAT sources"):
        SnowflakeConnectionManager._build_connection_parameters(_connection_definition())


def test_connection_rejects_missing_pat_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNOWFLAKE_TEST_PAT_TOKEN", raising=False)
    monkeypatch.delenv("SNOWFLAKE_TEST_PAT_SECRET_NAME", raising=False)

    with pytest.raises(RuntimeError, match="requires a PAT"):
        SnowflakeConnectionManager._build_connection_parameters(_connection_definition())


def test_connection_is_cached_by_connection_name(monkeypatch: pytest.MonkeyPatch) -> None:
    created_connections: list[FakeConnection] = []

    def fake_connect(**_: Any) -> FakeConnection:
        connection = FakeConnection()
        created_connections.append(connection)
        return connection

    monkeypatch.setenv("SNOWFLAKE_TEST_PAT_TOKEN", "direct-pat")
    monkeypatch.delenv("SNOWFLAKE_TEST_PAT_SECRET_NAME", raising=False)
    monkeypatch.setattr(connection_module.snowflake.connector, "connect", fake_connect)
    manager = SnowflakeConnectionManager((_connection_definition(),))

    first = manager.get_connection("shared_connection")
    second = manager.get_connection("shared_connection")

    assert first is second
    assert len(created_connections) == 1


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


def _connection_definition() -> SnowflakeConnectionDefinition:
    return SnowflakeConnectionDefinition.model_validate(
        {
            "name": "shared_connection",
            "account": "example-account",
            "host": "example-account.snowflakecomputing.com",
            "warehouse": "DEV_WH",
            "database": "DEV_DB",
            "schema": "DEV_SCHEMA",
            "user": "SF_SVC_USER",
            "role": "PUBLIC",
            "authentication": {
                "directPatToken": "SNOWFLAKE_TEST_PAT_TOKEN",
                "secret": "SNOWFLAKE_TEST_PAT_SECRET_NAME",
            },
            "connectionOptions": {
                "clientSessionKeepAlive": True,
                "loginTimeout": 30,
                "networkTimeout": 60,
            },
        }
    )
