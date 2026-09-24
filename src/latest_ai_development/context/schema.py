"""Validate the runtime context declaration in config/context.yml."""

from __future__ import annotations

import keyword
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

CONTEXT_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[JsonValue],
    "object": dict[str, JsonValue],
}


def validate_context_name(name: str) -> None:
    """Keep generated schema fields usable as public Python attributes."""
    if (
        not name.isidentifier()
        or keyword.iskeyword(name)
        or name.startswith("_")
        or name.startswith("model_")
        or hasattr(BaseModel, name)
    ):
        raise ValueError(f"Invalid context field name '{name}'")


class ContextField(BaseModel):
    """One field, its request context source, and its value constraints."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    source: str = Field(pattern=r"^request\.context\.[a-zA-Z][a-zA-Z0-9_]*$")
    required: bool = False
    default: Any = None
    allowed_values: list[Any] | None = Field(default=None, min_length=1)

    def validate_value(self, value: Any) -> Any:
        """Validate values without coercing strings into numbers or booleans."""
        if value is None:
            if self.required:
                raise ValueError("a value is required")
            return None
        value = TypeAdapter(CONTEXT_TYPES[self.type]).validate_python(value, strict=True)
        if self.allowed_values is not None and value not in self.allowed_values:
            raise ValueError("value is not in allowed_values")
        return value

    @model_validator(mode="after")
    def validate_constraints(self) -> ContextField:
        """Reject invalid defaults, allowed values, and source definitions early."""
        validate_context_name(self.source.rsplit(".", 1)[-1])
        adapter = TypeAdapter(CONTEXT_TYPES[self.type])
        for value in self.allowed_values or []:
            adapter.validate_python(value, strict=True)
        if "default" in self.model_fields_set:
            self.validate_value(self.default)
        return self


class RuntimeContextConfiguration(BaseModel):
    """Read-only context is separate from mutable workflow inputs and outputs."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    read_only: Literal[True] = True
    fields: dict[str, ContextField] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fields(self) -> RuntimeContextConfiguration:
        """Reject ambiguous request fields before generating the API schema."""
        request_sources: set[str] = set()
        for name, definition in self.fields.items():
            validate_context_name(name)
            if definition.source in request_sources:
                raise ValueError(f"Duplicate context source '{definition.source}'")
            request_sources.add(definition.source)
        return self


class ContextConfiguration(BaseModel):
    """The top-level object in context.yml."""

    model_config = ConfigDict(extra="forbid")

    runtime_context: RuntimeContextConfiguration
