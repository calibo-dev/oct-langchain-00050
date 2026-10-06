"""Assemble LangChain tools from tools.yml factories and named connection.yml settings."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, InjectedToolArg, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model

from latest_ai_development.core.errors import ToolExecutionError
from latest_ai_development.core.settings import CONFIG_DIR

from .connection import ConnectionManager, load_entries, resolve_tool_config


class ToolConfiguration(BaseModel):
    """One tools.yml entry, with its mapping key supplied as the name."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    factory: str = Field(min_length=1)
    connection_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    display_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    usage_guidelines: list[str] = Field(default_factory=list)
    non_usage_guidelines: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ToolDefinition:
    """A provider callable and input schema before LangChain adaptation."""

    name: str
    description: str
    input_schema: type[BaseModel]
    execute: Callable[..., Any]
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    async_execute: Callable[..., Awaitable[Any]] | None = None
    uses_context: bool = False


def build_tool_description(configuration: ToolConfiguration, context: Iterable[str] = ()) -> str:
    """Combine tool guidance from YAML with provider connection context."""
    lines = [configuration.description, "", f"Purpose: {configuration.purpose}", ""]
    lines.extend(context)
    if configuration.usage_guidelines:
        lines.extend(["", "Usage guidelines:"])
        lines.extend(f"- {value}" for value in configuration.usage_guidelines)
    if configuration.non_usage_guidelines:
        lines.extend(["", "Non-usage guidelines:"])
        lines.extend(f"- {value}" for value in configuration.non_usage_guidelines)
    return "\n".join(lines)


def _format_result(result: Any) -> str:
    """Preserve text and serialize structured results for the model."""
    if isinstance(result, str):
        return result
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json")
    return json.dumps(result, default=str)


def create_langchain_tool(definition: ToolDefinition) -> StructuredTool:
    """Wrap a portable callable with LangChain schemas, context, and error handling."""
    input_schema = definition.input_schema
    if definition.uses_context:
        if {"runtime", "context"} & input_schema.model_fields.keys():
            raise ValueError(f"Tool '{definition.name}' cannot expose injected context as input")
        input_schema = create_model(
            f"{definition.name}_runtime_input",
            __base__=input_schema,
            runtime=(Annotated[Any, InjectedToolArg], ...),
        )

    def execute(**arguments: Any) -> str:
        try:
            return _format_result(definition.execute(**arguments))
        except ToolExecutionError:
            raise
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            raise ToolExecutionError(definition.name, reason) from exc

    def execute_with_context(runtime: ToolRuntime[Any], **arguments: Any) -> str:
        return execute(**arguments, context=runtime.context)

    async def execute_async(**arguments: Any) -> str:
        try:
            assert definition.async_execute is not None
            return _format_result(await definition.async_execute(**arguments))
        except ToolExecutionError:
            raise
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            raise ToolExecutionError(definition.name, reason) from exc

    async def execute_async_with_context(runtime: ToolRuntime[Any], **arguments: Any) -> str:
        return await execute_async(**arguments, context=runtime.context)

    coroutine = None
    if definition.async_execute is not None:
        coroutine = execute_async_with_context if definition.uses_context else execute_async
    return StructuredTool.from_function(
        func=execute_with_context if definition.uses_context else execute,
        coroutine=coroutine,
        name=definition.name,
        description=definition.description,
        args_schema=input_schema,
        tags=list(definition.tags),
        metadata=dict(definition.metadata),
    )


def _resolve_secret(name: str) -> str | None:
    """Supply the template's secret backend without coupling integrations to it."""
    from latest_ai_development.core.secrets_manager import SecretsManager

    return SecretsManager().get_secret(name)


class ToolsRegistry(Mapping[str, BaseTool]):
    """Native tool lookup with a shared connection owner for resource cleanup."""

    def __init__(
        self, tools: Mapping[str, BaseTool], manager: ConnectionManager | None = None
    ) -> None:
        self._tools = dict(tools)
        self._manager = manager

    def __getitem__(self, name: str) -> BaseTool:
        return self._tools[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def get_tools(self) -> list[BaseTool]:
        """Return the tools when a LangChain caller needs a list."""
        return list(self._tools.values())

    def close(self) -> None:
        """Close shared provider connections at application shutdown."""
        if self._manager is not None:
            self._manager.close()


def build_tools_registry(
    tool_names: Iterable[str] | None = None,
    config_dir: Path = CONFIG_DIR,
    resolve_secret: Callable[[str], str | None] | None = None,
) -> ToolsRegistry:
    """Resolve both YAML files, call shared factories, and adapt the selected tools."""
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
            metadata = {
                key: value
                for key, value in resolved.items()
                if key not in {"connector", "configuration"}
            }
            configuration = ToolConfiguration.model_validate({**metadata, "name": name})
            factory = _load_factory(configuration.factory)
            definition = factory(tool_name=name, tool_config=resolved, connection_manager=manager)
            if not isinstance(definition, ToolDefinition) or definition.name != name:
                raise ValueError(f"Factory for '{name}' must return a matching ToolDefinition")
            tools[name] = create_langchain_tool(definition)
    except Exception:
        manager.close()
        raise
    return ToolsRegistry(tools, manager)


def _load_factory(reference: str) -> Callable[..., ToolDefinition]:
    """Load an explicitly configured factory from this template's tools package."""
    if not re.fullmatch(
        r"latest_ai_development\.tools\.[a-z][a-z0-9_]*:[a-z][a-z0-9_]*", reference
    ):
        raise ValueError("Tool factory must use 'latest_ai_development.tools.<module>:<function>'")
    module_name, function_name = reference.split(":")
    factory = getattr(import_module(module_name), function_name, None)
    if not callable(factory):
        raise ValueError(f"Configured tool factory '{reference}' is not callable")
    return factory
