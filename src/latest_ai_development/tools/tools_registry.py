"""Adapt portable tool definitions to this template's LangChain runtime."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langchain.tools import ToolRuntime
from langchain_core.tools import InjectedToolArg, StructuredTool
from pydantic import BaseModel, create_model

from latest_ai_development.core.errors import ToolExecutionError

if TYPE_CHECKING:
    from .tools_manager import ToolDefinition, ToolSetup, ToolsManager


def _format_result(result: Any) -> str:
    """Keep text intact and serialize portable structured results for model messages."""
    if isinstance(result, str):
        return result
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json")
    return json.dumps(result, default=str)


def adapt_tool(definition: ToolDefinition) -> StructuredTool:
    """Build a native tool without changing the portable operation's execution policy."""
    input_schema = definition.input_schema
    if definition.uses_context:
        if "runtime" in input_schema.model_fields:
            raise ValueError(f"Tool '{definition.name}' uses LangChain's reserved runtime argument")
        # Explicit schemas must declare injected arguments too, or LangChain's
        # input validation discards them before calling the operation wrapper.
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
    )


class ToolsRegistry(Mapping[str, StructuredTool]):
    """Framework-native tool lookup and lifecycle owned by the template."""

    def __init__(
        self,
        tools: Mapping[str, StructuredTool],
        manager: ToolsManager | None = None,
    ) -> None:
        self._tools = dict(tools)
        self._manager = manager

    def __getitem__(self, name: str) -> StructuredTool:
        return self._tools[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def close(self) -> None:
        """Release shared integration resources when the application stops."""
        if self._manager is not None:
            self._manager.close()


def load_tools_configuration(
    config_dir: Path, tool_names: Iterable[str]
) -> ToolSetup | None:
    """Skip optional skill assets entirely when the workflow has no tools."""
    selected = tuple(tool_names)
    if not selected:
        return None
    try:
        from .tools_manager import load_configuration
    except ModuleNotFoundError as exc:
        raise ValueError("Active agents require tools_manager.py and its dependencies") from exc
    return load_configuration(config_dir, selected)


def build_tools_registry(
    configuration: ToolSetup | None,
    resolve_secret: Callable[[str], str | None] | None = None,
) -> ToolsRegistry:
    """Convert portable definitions to LangChain tools without owning integration logic."""
    if configuration is None or not configuration.tools:
        return ToolsRegistry({})
    from .tools_manager import build_tools_manager

    manager = build_tools_manager(configuration, resolve_secret)
    try:
        tools = {tool.name: adapt_tool(tool) for tool in manager.all()}
    except Exception:
        manager.close()
        raise
    return ToolsRegistry(tools, manager)
