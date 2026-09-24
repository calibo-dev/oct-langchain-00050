"""Load and query model configuration from models.yaml."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from latest_ai_development.agents.schema import AgentModel
from latest_ai_development.core.settings import CONFIG_DIR, load_yaml_file
from latest_ai_development.models.schema import ModelsConfiguration, ProviderDefinition
from latest_ai_development.models.validator import validate_models_configuration


def load_models_configuration(
    required_models: Iterable[AgentModel] | None = None,
) -> ModelsConfiguration:
    """Load all models or only models referenced by active agents."""
    raw_configuration = load_yaml_file(CONFIG_DIR / "models.yaml")
    if required_models is not None:
        raw_configuration = _select_required_models(
            raw_configuration,
            required_models,
        )

    return validate_models_configuration(raw_configuration)


def model_exists(
    configuration: ModelsConfiguration,
    provider_name: str,
    model_name: str,
) -> bool:
    """Return whether a provider and model exist in the loaded configuration."""
    provider = _find_provider(configuration, provider_name)
    return provider is not None and model_name in provider.models


def get_model_parameters(
    configuration: ModelsConfiguration,
    provider_name: str,
    model_name: str,
) -> dict[str, Any]:
    """Return provider parameters for one configured model."""
    provider = _find_provider(configuration, provider_name)
    if provider is None:
        raise ValueError(f"Provider '{provider_name}' is not configured in models.yaml")

    model = provider.models.get(model_name)
    if model is None:
        raise ValueError(
            f"Model '{model_name}' is not configured for provider '{provider_name}' in models.yaml"
        )

    return model.parameters.as_provider_parameters()


def _find_provider(
    configuration: ModelsConfiguration,
    provider_name: str,
) -> ProviderDefinition | None:
    """Find a provider using a case-insensitive name."""
    provider_key = provider_name.strip().lower()
    for configured_name, provider in configuration.providers.items():
        if configured_name.strip().lower() == provider_key:
            return provider
    return None


def _select_required_models(
    raw_configuration: dict[str, Any],
    required_models: Iterable[AgentModel],
) -> dict[str, Any]:
    """Keep only model records referenced by active agents."""
    raw_providers = raw_configuration.get("providers")
    if not isinstance(raw_providers, dict):
        raise ValueError("models.yaml must contain a 'providers' mapping")

    provider_names_by_key = {
        str(provider_name).strip().lower(): provider_name for provider_name in raw_providers
    }
    selected_providers: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for model in required_models:
        provider_key = model.provider.strip().lower()
        configured_provider_name = provider_names_by_key.get(provider_key)
        if configured_provider_name is None:
            errors.append(f"provider '{model.provider}' is not configured in models.yaml")
            continue

        raw_provider = raw_providers.get(configured_provider_name)
        raw_models = raw_provider.get("models") if isinstance(raw_provider, dict) else None
        if not isinstance(raw_models, dict):
            errors.append(f"provider '{configured_provider_name}' must contain a 'models' mapping")
            continue

        raw_model = raw_models.get(model.model_id)
        if raw_model is None:
            errors.append(
                f"model '{model.model_id}' is not configured for provider "
                f"'{configured_provider_name}' in models.yaml"
            )
            continue

        provider_name = str(configured_provider_name)
        selected_provider = selected_providers.setdefault(
            provider_name,
            {"models": {}},
        )
        selected_provider["models"][model.model_id] = raw_model

    if errors:
        raise ValueError("Invalid models.yaml configuration:\n- " + "\n- ".join(errors))

    return {"providers": selected_providers}


__all__ = [
    "get_model_parameters",
    "load_models_configuration",
    "model_exists",
]
