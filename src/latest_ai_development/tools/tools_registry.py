"""Assemble LangChain tools from tools.yml factories and named connection.yml settings."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from importlib import import_module
from inspect import signature
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from latest_ai_development.core.settings import CONFIG_DIR

from .connection import ConnectionManager, load_entries, resolve_tool_config


def _resolve_secret(name: str) -> str | None:
    """Supply the template's secret backend without coupling integrations to it."""
    from latest_ai_development.core.secrets_manager import SecretsManager

    return SecretsManager().get_secret(name)


class ToolsRegistry(dict[str, BaseTool]):
    """A dictionary of native tools with application-owned connection cleanup."""

    def __init__(
        self, tools: Mapping[str, BaseTool], manager: ConnectionManager | None = None
    ) -> None:
        super().__init__(tools)
        self._manager = manager

    def get_tools(self) -> list[BaseTool]:
        """Return the tools when a LangChain caller needs a list."""
        return list(self.values())

    def close(self) -> None:
        """Close shared provider connections at application shutdown."""
        if self._manager is not None:
            self._manager.close()


def build_tools_registry(
    tool_names: Iterable[str] | None = None,
    config_dir: Path = CONFIG_DIR,
    resolve_secret: Callable[[str], str | None] | None = None,
) -> ToolsRegistry:
    """Resolve both YAML files and cache the native tools returned by their factories."""
    selected = None if tool_names is None else tuple(dict.fromkeys(tool_names))
    if selected == ():
        return ToolsRegistry({})
    entries = load_entries(config_dir / "tools.yml", "tools")
    selected = tuple(entries) if selected is None else selected
    missing = set(selected) - entries.keys()
    if missing:
        raise ValueError(f"Missing workflow tools: {sorted(missing)}")
    if not selected:
        return ToolsRegistry({})
    manager = ConnectionManager(config_dir, resolve_secret or _resolve_secret)
    try:
        tools = {}
        for name in selected:
            if "name" in entries[name]:
                raise ValueError(f"Tool '{name}' must use its YAML mapping key as its name")
            resolved = resolve_tool_config(name, entries[name], manager.configurations)
            tools[name] = _load_configured_tool(name, resolved, manager)
    except Exception:
        manager.close()
        raise
    return ToolsRegistry(tools, manager)


def _load_configured_tool(
    tool_name: str, tool_config: Mapping[str, Any], manager: ConnectionManager
) -> BaseTool:
    """Call a YAML factory using the same signature-based approach as LangGraph."""
    reference = tool_config.get("factory")
    if not isinstance(reference, str):
        raise ValueError(f"Tool '{tool_name}' requires a factory reference")
    module_name, separator, attribute_name = reference.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError(f"Tool factory '{reference}' must use '<module>:<attribute>' format")
    factory: Any = import_module(module_name)
    for part in attribute_name.split("."):
        factory = getattr(factory, part)
    if not callable(factory):
        raise ValueError(f"Configured tool factory '{reference}' is not callable")
    kwargs = tool_config.get("factory_kwargs", {})
    if not isinstance(kwargs, Mapping):
        raise ValueError(f"Tool '{tool_name}' factory_kwargs must be a mapping")
    if {"tool_name", "tool_config", "connection_manager"} & kwargs.keys():
        raise ValueError(f"Tool '{tool_name}' factory_kwargs must not override resolved wiring")
    resolved_kwargs = dict(kwargs)
    parameters = signature(factory).parameters
    for key, value in (
        ("tool_name", tool_name),
        ("tool_config", dict(tool_config)),
        ("connection_manager", manager),
    ):
        if key in parameters:
            resolved_kwargs[key] = value
    tool = factory(**resolved_kwargs)
    if not isinstance(tool, BaseTool) or tool.name != tool_name:
        raise ValueError(f"Factory for '{tool_name}' must return a matching LangChain tool")
    return tool
