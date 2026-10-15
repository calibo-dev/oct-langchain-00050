"""Expose context to the model only through explicit YAML prompt references."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from latest_ai_development.context.runtime import render_context_prompt


class ContextPromptMiddleware(AgentMiddleware):
    """Render a fresh system prompt for each invocation without shared mutations."""

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt

    def _prepare_request(self, request: ModelRequest) -> ModelRequest:
        prompt = render_context_prompt(self.prompt, request.runtime.context)
        return request.override(system_message=SystemMessage(content=prompt))

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        """Resolve context references before a synchronous model invocation."""
        return handler(self._prepare_request(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        """Resolve context references before an asynchronous model invocation."""
        return await handler(self._prepare_request(request))
