"""Shared exceptions for agent output validation and tool execution."""


class InvalidAgentOutputError(ValueError):
    """Raised when a model attempt does not satisfy its agent output contract."""


class ToolExecutionError(RuntimeError):
    """Raised when a tool failure must stop execution without model fallback."""

    def __init__(self, tool_name: str, reason: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {reason}")
