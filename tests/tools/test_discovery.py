"""Check folder discovery and generic construction without external services."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from latest_ai_development.connections import config as connection_config
from latest_ai_development.connections.factory import build_connection_registry
from latest_ai_development.tools import config as tool_config
from latest_ai_development.tools import discovery
from latest_ai_development.tools.factory import build_tool_registry
from latest_ai_development.tools.schema import BaseToolDefinition
from latest_ai_development.tools.snowflake.plugin import plugin as snowflake_plugin


class ExampleConnections(BaseModel):
    connections: list[dict[str, str]]


@pytest.fixture(autouse=True)
def reset_discovery():
    discovery.discover_connectors.cache_clear()
    yield
    discovery.discover_connectors.cache_clear()


def test_installed_snowflake_is_discovered_once():
    plugins = discovery.discover_connectors()
    assert plugins["snowflake"] is snowflake_plugin
    assert discovery.discover_connectors() is plugins
    with pytest.raises(TypeError):
        plugins["other"] = snowflake_plugin


def test_second_connector_needs_no_central_registration(tmp_path, monkeypatch):
    # A new folder is the registration mechanism. Mock its import to isolate
    # discovery and configuration routing from any vendor dependency.
    directory = tmp_path / "example"
    directory.mkdir()
    (directory / "plugin.py").touch()
    manager = Mock()
    tool = Mock()
    plugin = replace(
        snowflake_plugin,
        name="example",
        validate_connections=ExampleConnections.model_validate,
        validate_tool=lambda raw: BaseToolDefinition.model_validate(raw),
        build_manager=lambda configuration: manager,
        build_tool=lambda settings, definition, shared: tool if shared is manager else None,
    )
    monkeypatch.setattr(discovery, "CONNECTOR_DIRECTORY", tmp_path)
    importer = Mock(return_value=SimpleNamespace(plugin=plugin))
    monkeypatch.setattr(discovery, "import_module", importer)
    monkeypatch.setattr(tool_config, "TOOLS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(connection_config, "TOOLS_CONFIG_DIR", tmp_path)
    (tmp_path / "example_tools.yaml").write_text(
        "tools:\n  - name: example_query\n    connector: example\n"
        "    connectionName: shared\n    description: Query data\n    purpose: Answer questions\n"
    )
    (tmp_path / "example_connections.yaml").write_text("connections:\n  - name: shared\n")

    tools = tool_config.load_tools_configuration(["example_query"])
    connections = connection_config.load_connections_configuration(
        tool_config.collect_connection_names(tools)
    )
    registry = build_connection_registry(connections)
    result = build_tool_registry(SimpleNamespace(), tools, registry)
    assert result.get(["example_query"]) == (tool,)
    assert registry.get("example") is manager
    registry.close()
    manager.close.assert_called_once()
    importer.assert_called_once_with("latest_ai_development.tools.example.plugin")


def test_bad_plugin_fails_with_connector_name(tmp_path, monkeypatch):
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "plugin.py").touch()
    monkeypatch.setattr(discovery, "CONNECTOR_DIRECTORY", tmp_path)
    monkeypatch.setattr(discovery, "import_module", lambda name: SimpleNamespace())
    with pytest.raises(ValueError, match="Connector 'broken'"):
        discovery.discover_connectors()


def test_unknown_connector_is_rejected():
    with pytest.raises(ValueError, match="Unknown connector"):
        discovery.get_connector("missing")


def test_snowflake_config_still_builds_without_connecting():
    tools = tool_config.load_tools_configuration(["country_data_agentic_tool"])
    connections = connection_config.load_connections_configuration(
        tool_config.collect_connection_names(tools)
    )
    registry = build_connection_registry(connections)
    result = build_tool_registry(SimpleNamespace(), tools, registry)
    assert result.get(["country_data_agentic_tool"])[0].name == "country_data_agentic_tool"
    assert registry.get("snowflake")._connections == {}
    registry.close()
