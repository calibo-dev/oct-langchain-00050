"""Runtime behavior shared by primary and fallback LangChain agents."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.agents.middleware.types import ToolCallRequest
from langgraph.types import Command

from latest_ai_development.core.errors import ToolExecutionError

logger = logging.getLogger(__name__)


class StrictToolCallingMiddleware(AgentMiddleware):
    """Ask OpenAI-compatible models to use strict tool schemas."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Any,
    ) -> ModelResponse:
        """Enable strict tool conversion before the model is bound to tools."""
        request.model_settings = {
            **request.model_settings,
            "strict": True,
        }
        return handler(request)


class ToolFailureMiddleware(AgentMiddleware):
    """Stop the agent when tool execution raises or returns an error message."""

    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """Convert tool failures into errors that bypass model fallback."""
        tool_name = request.tool_call["name"]
        try:
            result = handler(request)
        except ToolExecutionError:
            raise
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            raise ToolExecutionError(tool_name, reason) from exc
        _raise_for_tool_error(result, tool_name)
        return result

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """Apply the same tool failure policy during asynchronous execution."""
        tool_name = request.tool_call["name"]
        try:
            result = await handler(request)
        except ToolExecutionError:
            raise
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            raise ToolExecutionError(tool_name, reason) from exc
        _raise_for_tool_error(result, tool_name)
        return result


def _raise_for_tool_error(result: Any, tool_name: str = "unknown") -> None:
    """Recognize explicit tool errors, including messages returned in commands."""
    if isinstance(result, Command):
        if isinstance(result.update, Mapping):
            _raise_for_tool_error(result.update.get("messages", []), tool_name)
        return
    if isinstance(result, (list, tuple)):
        for message in result:
            _raise_for_tool_error(message, tool_name)
        return
    if isinstance(result, Mapping):
        message_type = result.get("type") or result.get("role")
        status = result.get("status")
        name = result.get("name") or tool_name
    else:
        message_type = getattr(result, "type", None)
        status = getattr(result, "status", None)
        name = getattr(result, "name", None) or tool_name
    if message_type == "tool" and status == "error":
        raise ToolExecutionError(name, "tool returned an error response")


@dataclass(frozen=True)
class AgentRuntime:
    """Primary and fallback runtime agents for one configured agent."""

    name: str
    agents: tuple[Any, ...]
    model_names: tuple[str, ...]

    def invoke(
        self,
        inputs: dict[str, Any],
        config: Mapping[str, Any] | None = None,
        *,
        validate_result: Callable[[Any], Any] | None = None,
        context: Any = None,
    ) -> Any:
        """Try models until output is valid, stopping immediately on tool failure."""
        last_error: Exception | None = None

        for agent_index, agent in enumerate(self.agents):
            agent_config = _build_runtime_agent_config(
                config,
                self.model_names[agent_index],
                agent_index > 0,
            )
            try:
                context_options = {"context": context} if context is not None else {}
                result = agent.invoke(inputs, config=agent_config, **context_options)
                if isinstance(result, Mapping):
                    _raise_for_tool_error(result.get("messages", []))
                return validate_result(result) if validate_result is not None else result
            except ToolExecutionError:
                raise
            except Exception as exc:
                last_error = exc
                if agent_index < len(self.agents) - 1:
                    logger.warning(
                        "Agent attempt failed; trying fallback agent=%s model=%s",
                        self.name,
                        self.model_names[agent_index],
                    )
                    continue
                raise

        raise RuntimeError(f"No runtime agent is available for '{self.name}'") from last_error


def _build_runtime_agent_config(
    config: Mapping[str, Any] | None,
    model_name: str,
    is_fallback: bool,
) -> dict[str, Any] | None:
    """Add runtime model details to a LangChain invoke config."""
    if config is None:
        return None

    agent_config = dict(config)
    metadata = dict(agent_config.get("metadata") or {})
    tags = list(agent_config.get("tags") or [])

    metadata["model"] = model_name
    metadata["is_fallback_model"] = is_fallback
    tags.append("fallback-model" if is_fallback else "primary-model")

    agent_config["metadata"] = metadata
    agent_config["tags"] = tags
    return agent_config


__all__ = ["AgentRuntime", "StrictToolCallingMiddleware", "ToolFailureMiddleware"]
