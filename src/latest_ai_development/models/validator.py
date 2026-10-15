"""Validate raw models.yaml data with Pydantic."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from latest_ai_development.models.schema import ModelsConfiguration


def validate_models_configuration(
    raw_configuration: dict[str, Any],
) -> ModelsConfiguration:
    """Convert raw models.yaml data into checked Pydantic objects."""
    try:
        return ModelsConfiguration.model_validate(raw_configuration)
    except ValidationError as exc:
        raise ValueError(f"Invalid models.yaml configuration:\n{exc}") from exc
