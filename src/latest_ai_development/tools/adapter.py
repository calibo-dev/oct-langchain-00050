"""Adapt portable tool definitions to this template's LangChain runtime."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any

from langchain.tools import ToolRuntime
from langchain_core.tools import InjectedToolArg, StructuredTool
from pydantic import BaseModel, create_model

from latest_ai_development.core.errors import ToolExecutionError

if TYPE_CHECKING:
    from .manager import ToolDefinition, ToolRegistry


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


def adapt_tools(registry: ToolRegistry) -> dict[str, StructuredTool]:
    """Create the native tool lookup consumed by the agent factory."""
    return {tool.name: adapt_tool(tool) for tool in registry.all()}
