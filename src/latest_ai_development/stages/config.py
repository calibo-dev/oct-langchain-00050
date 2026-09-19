"""Load workflow-stage configuration from stages.yaml."""

from __future__ import annotations

from pydantic import ValidationError

from latest_ai_development.core.settings import CONFIG_DIR, load_yaml_file
from latest_ai_development.stages.schema import WorkflowDefinition


def load_workflow_definition() -> WorkflowDefinition:
    """Load and validate the workflow definition from stages.yaml."""
    raw_configuration = load_yaml_file(CONFIG_DIR / "stages.yaml")
    workflow_configuration = raw_configuration.get("workflow")
    if not isinstance(workflow_configuration, dict):
        raise ValueError("stages.yaml must contain a 'workflow' mapping")

    try:
        return WorkflowDefinition.model_validate(workflow_configuration)
    except ValidationError as exc:
        raise ValueError(f"Invalid stages.yaml configuration:\n{exc}") from exc


__all__ = ["load_workflow_definition"]
