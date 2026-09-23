"""Pydantic models for the values stored in config/models.yaml."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class ProviderModels(BaseModel):
    """One primary model and zero or more ordered fallback models."""

    model_config = ConfigDict(extra="forbid")

    primary: dict[str, ModelDefinition]
    fallback: dict[str, ModelDefinition] = Field(default_factory=dict)

    @field_validator("primary")
    @classmethod
    def validate_primary(
        cls,
        models: dict[str, ModelDefinition],
    ) -> dict[str, ModelDefinition]:
        """Require exactly one primary model for the provider."""
        if len(models) != 1:
            raise ValueError("primary must contain exactly one model")

        _validate_model_names(models)
        return models

    @field_validator("fallback")
    @classmethod
    def validate_fallbacks(
        cls,
        models: dict[str, ModelDefinition],
    ) -> dict[str, ModelDefinition]:
        """Validate fallback names while keeping their YAML order."""
        _validate_model_names(models)
        return models

    @model_validator(mode="after")
    def validate_unique_models(self) -> ProviderModels:
        """Prevent the primary model from also being a fallback."""
        primary_model_name = next(iter(self.primary))
        if primary_model_name in self.fallback:
            raise ValueError("the primary model cannot also be a fallback model")
        return self

    def all_models(self) -> dict[str, ModelDefinition]:
        """Return primary first, followed by fallbacks in configured order."""
        return {**self.primary, **self.fallback}


class ProviderDefinition(BaseModel):
    """All models configured for one provider, such as OpenAI."""

    model_config = ConfigDict(extra="forbid")

    models: ProviderModels


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
