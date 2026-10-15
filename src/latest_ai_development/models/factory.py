"""Create runtime language-model objects from validated configuration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from latest_ai_development.agents.schema import AgentModel
from latest_ai_development.core.settings import Settings
from latest_ai_development.models.config import get_model_parameters
from latest_ai_development.models.provider_builders import (
    PROVIDER_BUILDERS,
    SUPPORTED_PROVIDERS,
    normalize_provider_key,
)
from latest_ai_development.models.registry import ModelRegistry
from latest_ai_development.models.schema import ModelsConfiguration


def build_model_registry(
    settings: Settings,
    configuration: ModelsConfiguration,
    required_models: Iterable[AgentModel],
) -> ModelRegistry:
    """Create active model objects and return their read-only registry."""
    models: dict[tuple[str, str], Any] = {}

    for model in required_models:
        model_key = (normalize_provider_key(model.provider), model.model_id)
        if model_key in models:
            continue
        models[model_key] = create_llm(
            settings=settings,
            configuration=configuration,
            provider=model.provider,
            model_name=model.model_id,
        )

    return ModelRegistry(models)


def create_llm(
    settings: Settings,
    configuration: ModelsConfiguration,
    provider: str,
    model_name: str,
) -> Any:
    """Create one LLM using its validated models.yaml parameters."""
    parameters = get_model_parameters(configuration, provider, model_name)
    provider_key = normalize_provider_key(provider)
    provider_builder = PROVIDER_BUILDERS.get(provider_key)
    if provider_builder is None:
        raise ValueError(
            f"Unsupported provider '{provider}'. Expected one of: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return provider_builder(settings, model_name, parameters)


__all__ = ["build_model_registry", "create_llm"]
