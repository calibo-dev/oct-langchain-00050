"""Connector-neutral schemas shared by every configured tool family."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BaseToolDefinition(BaseModel):
    """Fields required for every tool, independent of its connector."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    connector: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    connection_name: str = Field(alias="connectionName", min_length=1)
    display_name: str | None = Field(default=None, alias="displayName")
    description: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    usage_guidelines: list[str] = Field(default_factory=list, alias="usageGuidelines")
    non_usage_guidelines: list[str] = Field(default_factory=list, alias="nonUsageGuidelines")

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_optional_display_name(cls, value: str | None) -> str | None:
        """Treat a blank optional display name as missing."""
        if value is None:
            return None
        normalized_value = str(value).strip()
        return normalized_value or None

    @field_validator("tags", "usage_guidelines", "non_usage_guidelines")
    @classmethod
    def validate_unique_text_values(cls, values: list[str]) -> list[str]:
        """Normalize list entries and reject empty or repeated values."""
        cleaned_values = [value.strip() for value in values]
        if any(not value for value in cleaned_values):
            raise ValueError("values must not be empty")
        if len(cleaned_values) != len(set(cleaned_values)):
            raise ValueError("values must be unique")
        return cleaned_values


class ToolsConfiguration(BaseModel):
    """Validated tools from one or more connector-specific YAML files."""

    model_config = ConfigDict(extra="forbid")

    tools: list[BaseToolDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_tool_names(self) -> Self:
        """Tool names are global registry keys and must be unique."""
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique across connectors")
        return self


__all__ = ["BaseToolDefinition", "ToolsConfiguration"]
