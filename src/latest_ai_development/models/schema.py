"""Pydantic models for the values stored in config/models.yaml."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelParameters(BaseModel):
    """Generation settings passed to an LLM provider."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # YAML uses common API names such as topP. Aliases let Python use snake_case.
    # Every value is optional. Missing values are not sent to the LLM provider.
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, alias="topP", ge=0, le=1)
    max_output_tokens: int | None = Field(default=None, alias="maxOutputTokens", gt=0)
    presence_penalty: float | None = Field(default=None, alias="presencePenalty", ge=-2, le=2)
    frequency_penalty: float | None = Field(
        default=None,
        alias="frequencyPenalty",
        ge=-2,
        le=2,
    )
    response_format: str | dict[str, Any] | None = Field(default=None, alias="responseFormat")
    additional_model_request_fields: dict[str, Any] | None = Field(
        default=None,
        alias="additionalModelRequestFields",
    )

    @field_validator("response_format")
    @classmethod
    def validate_response_format(
        cls,
        value: str | dict[str, Any] | None,
    ) -> str | dict[str, Any] | None:
        """Reject blank responseFormat values."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("responseFormat must not be empty")
        return value

    def as_provider_parameters(self) -> dict[str, Any]:
        """Return the original YAML-style names expected by the model factory."""
        return self.model_dump(by_alias=True, exclude_none=True)


class ModelDefinition(BaseModel):
    """Configuration for one model ID."""

    model_config = ConfigDict(extra="forbid")

    parameters: ModelParameters = Field(default_factory=ModelParameters)


class ProviderDefinition(BaseModel):
    """Shared model definitions for one provider, independent of agent order."""

    model_config = ConfigDict(extra="forbid")

    models: dict[str, ModelDefinition] = Field(min_length=1)

    @field_validator("models")
    @classmethod
    def validate_models(
        cls,
        models: dict[str, ModelDefinition],
    ) -> dict[str, ModelDefinition]:
        """Reject blank model names in the provider catalog."""
        _validate_model_names(models)
        return models


def _validate_model_names(models: dict[str, ModelDefinition]) -> None:
    """Reject blank model names."""
    for model_name in models:
        if not model_name.strip():
            raise ValueError("model names must not be empty")


class ModelsConfiguration(BaseModel):
    """The top-level object in models.yaml."""

    model_config = ConfigDict(extra="forbid")

    providers: dict[str, ProviderDefinition]

    @field_validator("providers")
    @classmethod
    def validate_providers(
        cls,
        providers: dict[str, ProviderDefinition],
    ) -> dict[str, ProviderDefinition]:
        """Reject empty provider sections and blank provider names."""
        if len(providers) == 0:
            raise ValueError("providers must contain at least one provider")

        for provider_name in providers:
            if not provider_name.strip():
                raise ValueError("provider names must not be empty")
        return providers
