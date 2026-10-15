"""Store and retrieve runtime language-model objects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ModelRegistry:
    """Read-only lookup for models created during application startup."""

    def __init__(self, models: Mapping[tuple[str, str], Any]) -> None:
        self._models = {
            (_normalize_provider_name(provider), model_name): model
            for (provider, model_name), model in models.items()
        }

    def get(self, provider_name: str, model_name: str) -> Any:
        """Return a runtime model by provider and model name."""
        model_key = (_normalize_provider_name(provider_name), model_name)
        try:
            return self._models[model_key]
        except KeyError as exc:
            raise KeyError(f"Model '{provider_name}/{model_name}' is not available") from exc

    def contains(self, provider_name: str, model_name: str) -> bool:
        """Return whether a runtime model is available."""
        model_key = (_normalize_provider_name(provider_name), model_name)
        return model_key in self._models

    def count(self) -> int:
        """Return the number of available runtime models."""
        return len(self._models)


def _normalize_provider_name(provider_name: str) -> str:
    return provider_name.strip().lower()


__all__ = ["ModelRegistry"]
