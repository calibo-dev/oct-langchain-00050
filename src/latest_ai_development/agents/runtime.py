"""Runtime behavior shared by primary and fallback LangChain agents."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

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
    ) -> Any:
        """Run the primary agent, then configured fallbacks after failures."""
        last_error: Exception | None = None

        for agent_index, agent in enumerate(self.agents):
            agent_config = _build_runtime_agent_config(
                config,
                self.model_names[agent_index],
                agent_index > 0,
            )
            try:
                return agent.invoke(inputs, config=agent_config)
            except Exception as exc:
                last_error = exc
                if agent_index < len(self.agents) - 1:
                    logger.warning(
                        "Agent invocation failed; trying fallback agent=%s model=%s",
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


__all__ = ["AgentRuntime", "StrictToolCallingMiddleware"]
