"""Convert portable tool definitions into LangChain tools and own their lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, InjectedToolArg, StructuredTool
from pydantic import BaseModel, create_model

from latest_ai_development.core.errors import ToolExecutionError
from latest_ai_development.core.settings import CONFIG_DIR

if TYPE_CHECKING:
    from .tools_manager import ToolDefinition, ToolsManager


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
    """Native tool lookup with a shared manager responsible for resource cleanup."""

    def __init__(
        self, tools: Mapping[str, BaseTool], manager: ToolsManager | None = None
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
        """Delegate resource cleanup to the framework-independent manager."""
        if self._manager is not None:
            self._manager.close()


def build_tools_registry(
    tool_names: Iterable[str] | None = None,
    config_dir: Path = CONFIG_DIR,
    resolve_secret: Callable[[str], str | None] | None = None,
) -> ToolsRegistry:
    """Create the workflow's selected tools without importing unused integration assets."""
    selected = None if tool_names is None else tuple(tool_names)
    if selected == ():
        return ToolsRegistry({})
    try:
        from .tools_manager import ToolsManager
    except ModuleNotFoundError as exc:
        raise ValueError("Active tools require tools_manager.py and its dependencies") from exc
    manager = ToolsManager(config_dir, resolve_secret or _resolve_secret)
    try:
        definitions = manager.create_tools(selected)
        tools = {definition.name: create_langchain_tool(definition) for definition in definitions}
    except Exception:
        manager.close()
        raise
    return ToolsRegistry(tools, manager)
