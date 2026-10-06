"""Exercise YAML assembly and the actual LangChain/API flow without external services."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from latest_ai_development.core.errors import ToolExecutionError
from latest_ai_development.core.settings import BASE_DIR, CONFIG_DIR, Settings
from latest_ai_development.tools.connection import ConnectionManager, load_entries
from latest_ai_development.tools.tools_registry import build_tools_registry

TOOL_NAMES = (
    "snowflake_table_hospitals",
    "snowflake_table_patients",
    "snowflake_table_doctors",
)


class FakeCursor:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.description = [("name",)]
        self.closed = False

    def execute(self, query: str) -> None:
        self.client.queries.append(query)
        self.description = [("name",)] if query.startswith("SHOW") else [("total",)]

    def fetchall(self) -> list[tuple[Any, ...]]:
        if self.description == [("total",)]:
            return [(7,)]
        return (
            [("DOCTORS",)]
            if "staff" in self.client.parameters["account"]
            else [("HOSPITALS",), ("PATIENTS",)]
        )

    def fetchmany(self, count: int) -> list[tuple[Any, ...]]:
        return self.fetchall()[:count]

    def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self, parameters: dict[str, Any]) -> None:
        self.parameters = parameters
        self.queries: list[str] = []
        self.cursors: list[FakeCursor] = []
        self.close_count = 0

    def cursor(self) -> FakeCursor:
        cursor = FakeCursor(self)
        self.cursors.append(cursor)
        return cursor

    def is_closed(self) -> bool:
        return self.close_count > 0

    def close(self) -> None:
        self.close_count += 1


@pytest.fixture
def snowflake_clients(monkeypatch: pytest.MonkeyPatch) -> list[FakeClient]:
    import snowflake.connector

    clients: list[FakeClient] = []

    def connect(**parameters: Any) -> FakeClient:
        client = FakeClient(parameters)
        clients.append(client)
        return client

    monkeypatch.setattr(snowflake.connector, "connect", connect)
    for prefix in ("SNOWFLAKE_HOSPITAL_CORE", "SNOWFLAKE_HOSPITAL_STAFF"):
        monkeypatch.setenv(f"{prefix}_PAT_TOKEN", f"dummy-{prefix}")
        monkeypatch.setenv(f"{prefix}_PAT_SECRET_NAME", "")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    return clients


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    for name in ("tools.yml", "connection.yml"):
        (tmp_path / name).write_text((CONFIG_DIR / name).read_text(), encoding="utf-8")
    return tmp_path


def test_three_tools_share_two_lazy_connections(snowflake_clients: list[FakeClient]) -> None:
    registry = build_tools_registry((*TOOL_NAMES, TOOL_NAMES[0]))
    try:
        assert tuple(registry) == TOOL_NAMES
        assert snowflake_clients == []  # Startup does not authenticate or open clients.
        assert "Hospital Data" not in registry[TOOL_NAMES[1]].description
        assert "admissions" in registry[TOOL_NAMES[1]].description
        assert "Non-usage guidelines" in registry[TOOL_NAMES[0]].description
        assert registry[TOOL_NAMES[0]].metadata["connection_name"] == "hospital_core_connection"

        for name in TOOL_NAMES:
            registry[name].invoke({"metadata_scope": "tables", "row_limit": 5})
        assert len(snowflake_clients) == 2
        core, staff = snowflake_clients
        assert len(core.queries) == 2
        assert len(staff.queries) == 1
        assert core.parameters["password"] == "dummy-SNOWFLAKE_HOSPITAL_CORE"
        assert staff.parameters["password"] == "dummy-SNOWFLAKE_HOSPITAL_STAFF"
        assert core.parameters["account"] == "your_core_account"
        result = registry[TOOL_NAMES[1]].invoke({"query": "SELECT COUNT(*) AS total FROM PATIENTS"})
        assert "7" in result
        assert core.queries[-1].endswith("LIMIT 1000;")
        assert len(snowflake_clients) == 2
    finally:
        registry.close()
        registry.close()
    assert all(client.close_count == 1 for client in snowflake_clients)
    assert all(cursor.closed for client in snowflake_clients for cursor in client.cursors)


def test_mutating_sql_is_rejected_before_connecting(snowflake_clients: list[FakeClient]) -> None:
    registry = build_tools_registry([TOOL_NAMES[0]])
    try:
        with pytest.raises(ToolExecutionError, match="query_execution_failed"):
            registry[TOOL_NAMES[0]].invoke({"query": "DELETE FROM HOSPITALS"})
        assert snowflake_clients == []
    finally:
        registry.close()


@pytest.mark.parametrize("mode", ["missing", "both", "secret"])
def test_pat_sources(
    mode: str, monkeypatch: pytest.MonkeyPatch, snowflake_clients: list[FakeClient]
) -> None:
    monkeypatch.setenv("SNOWFLAKE_HOSPITAL_CORE_PAT_TOKEN", "dummy" if mode == "both" else "")
    monkeypatch.setenv(
        "SNOWFLAKE_HOSPITAL_CORE_PAT_SECRET_NAME", "" if mode == "missing" else "pat-secret"
    )
    resolved: list[str] = []

    def resolve_secret(name: str) -> str:
        resolved.append(name)
        return "dummy-from-secret-backend"

    registry = build_tools_registry([TOOL_NAMES[0]], resolve_secret=resolve_secret)
    try:
        if mode == "secret":
            registry[TOOL_NAMES[0]].invoke({"metadata_scope": "tables"})
            assert resolved == ["pat-secret"]
            assert snowflake_clients[0].parameters["password"] == "dummy-from-secret-backend"
        else:
            with pytest.raises(ToolExecutionError, match="metadata_discovery_failed"):
                registry[TOOL_NAMES[0]].invoke({"metadata_scope": "tables"})
            assert snowflake_clients == []
            assert resolved == []
    finally:
        registry.close()


def test_explicit_environment_name_and_file_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("MY_CUSTOM_PAT=dummy-from-file\n", encoding="utf-8")
    monkeypatch.delenv("MY_CUSTOM_PAT", raising=False)
    manager = ConnectionManager(CONFIG_DIR, env_file=env_file)
    assert manager.read_environment("MY_CUSTOM_PAT") == "dummy-from-file"
    monkeypatch.setenv("MY_CUSTOM_PAT", "dummy-from-process")
    assert manager.read_environment("MY_CUSTOM_PAT") == "dummy-from-process"
    monkeypatch.setenv("MY_CUSTOM_PAT", "")
    assert manager.read_environment("MY_CUSTOM_PAT") == ""


@pytest.mark.parametrize(
    "defect", ["unknown_connection", "inline", "provider", "account", "factory"]
)
def test_invalid_wiring_fails_during_startup(config_dir: Path, defect: str) -> None:
    tools_path = config_dir / "tools.yml"
    connections_path = config_dir / "connection.yml"
    tools = yaml.safe_load(tools_path.read_text())
    connections = yaml.safe_load(connections_path.read_text())
    entry = tools["tools"][TOOL_NAMES[0]]
    core = connections["connections"]["hospital_core_connection"]
    if defect == "unknown_connection":
        entry["connection_name"] = "does_not_exist"
    elif defect == "inline":
        entry["configuration"] = {"account": "wrong"}
    elif defect == "provider":
        core["connector"]["type"] = "DATABRICKS"
    elif defect == "account":
        del core["configuration"]["account"]
    else:
        entry["factory"] = "missing_factory"
    tools_path.write_text(yaml.safe_dump(tools), encoding="utf-8")
    connections_path.write_text(yaml.safe_dump(connections), encoding="utf-8")
    with pytest.raises(ValueError):
        build_tools_registry([TOOL_NAMES[0]], config_dir)


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "tools.yml"
    path.write_text("tools:\n  duplicate: {}\n  duplicate: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_entries(path, "tools")


def test_empty_selection_needs_no_connector_files(tmp_path: Path) -> None:
    assert len(build_tools_registry([], tmp_path)) == 0


def test_only_selected_connections_are_validated(config_dir: Path) -> None:
    path = config_dir / "connection.yml"
    connections = yaml.safe_load(path.read_text())
    connections["connections"]["hospital_staff_connection"]["configuration"] = {}
    path.write_text(yaml.safe_dump(connections), encoding="utf-8")
    registry = build_tools_registry([TOOL_NAMES[0]], config_dir)
    try:
        assert tuple(registry) == (TOOL_NAMES[0],)
    finally:
        registry.close()


class ScriptedModel(BaseChatModel):
    """Simulate the LLM only; LangChain chooses and executes real configured tools."""

    @property
    def _llm_type(self) -> str:
        return "offline-integration-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        assert {tool.name for tool in tools} == set(TOOL_NAMES)
        return self

    def _generate(self, messages: list[Any], **kwargs: Any) -> ChatResult:
        tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
        if "Review the supplied draft" in messages[0].content:
            assert "7 rows in each source" in messages[-1].content
            message = AIMessage(content=json.dumps({"final_response": "7 rows in each source"}))
        elif len(tool_messages) < 6:
            query_round = len(tool_messages) == 3
            if query_round:
                assert "HOSPITALS" in tool_messages[0].content
                assert "PATIENTS" in tool_messages[1].content
                assert "DOCTORS" in tool_messages[2].content
            calls = []
            for index, name in enumerate(TOOL_NAMES):
                args = {"metadata_scope": "tables", "row_limit": 5}
                if query_round:
                    table = ("HOSPITALS", "PATIENTS", "DOCTORS")[index]
                    args = {"query": f"SELECT COUNT(*) AS total FROM EXAMPLE.PUBLIC.{table}"}
                calls.append({"name": name, "args": args, "id": f"call-{query_round}-{index}"})
            message = AIMessage(content="", tool_calls=calls)
        else:
            assert all("7" in result.content for result in tool_messages[3:])
            message = AIMessage(content=json.dumps({"draft": "7 rows in each source"}))
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_full_fastapi_langchain_workflow(
    monkeypatch: pytest.MonkeyPatch, snowflake_clients: list[FakeClient]
) -> None:
    from latest_ai_development.application import create_app
    from latest_ai_development.core.container import get_application_container
    from latest_ai_development.core.container_builder import ApplicationContainerBuilder
    from latest_ai_development.models.registry import ModelRegistry

    # Keep settings and model objects deterministic; no real .env, keys, or cloud calls.
    settings = Settings(_env_file=None, **dotenv_values(BASE_DIR / ".env.example"))
    monkeypatch.setattr(ApplicationContainerBuilder, "_load_settings", lambda self: settings)
    models = ModelRegistry(
        {
            ("OpenAI", "gpt-4.1"): ScriptedModel(),
            ("OpenAI", "gpt-4.1-mini"): ScriptedModel(),
        }
    )
    monkeypatch.setattr(ApplicationContainerBuilder, "_build_models", lambda *args: models)
    get_application_container.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health").status_code == 200
            response = client.post(
                "/langchain_python_template", json={"topic": "Count all sources"}
            )
            assert response.status_code == 200, response.text
            assert response.json() == {"final_response": "7 rows in each source"}
            assert len(snowflake_clients) == 2
            assert sorted(len(connection.queries) for connection in snowflake_clients) == [2, 4]
            assert client.post("/langchain_python_template", json={"topic": ""}).status_code == 422
        assert all(connection.close_count == 1 for connection in snowflake_clients)
    finally:
        get_application_container.cache_clear()
