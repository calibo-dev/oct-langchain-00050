"""Workflow-specific exceptions."""


class WorkflowExecutionError(RuntimeError):
    """Raised when the configured workflow cannot complete."""
