"""Resolve and freeze configured context once for each workflow request."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import make_dataclass
from types import MappingProxyType
from typing import Any

from pydantic import ConfigDict, Field, ValidationError, create_model

from latest_ai_development.context.schema import CONTEXT_TYPES, RuntimeContextConfiguration

CONTEXT_REFERENCE = re.compile(r"\{context\.([a-zA-Z][a-zA-Z0-9_]*)\}")


class ContextValidationError(ValueError):
    """Request context cannot satisfy the configured field contract."""


class ContextRuntime:
    """Build reusable schemas while keeping resolved values request-local."""

    def __init__(self, configuration: RuntimeContextConfiguration) -> None:
        self.configuration = configuration
        self.schema = make_dataclass(
            "RuntimeContext",
            [(name, Any) for name in configuration.fields],
            frozen=True,
            slots=True,
        )
        request_fields: dict[str, Any] = {}
        for definition in configuration.fields.values():
            name = definition.source.rsplit(".", 1)[-1]
            field_type = CONTEXT_TYPES[definition.type]
            default = definition.default
            if definition.required and "default" not in definition.model_fields_set:
                default = ...
            if not definition.required:
                field_type = field_type | None
            schema_extra = None
            if definition.allowed_values is not None:
                allowed_values = list(definition.allowed_values)
                if not definition.required:
                    allowed_values.append(None)
                schema_extra = {"enum": allowed_values}
            request_fields[name] = (
                field_type,
                Field(default=default, json_schema_extra=schema_extra),
            )
        self.request_model = create_model(
            "WorkflowContextRequest",
            __config__=ConfigDict(extra="forbid", strict=True),
            **request_fields,
        )

    def resolve(
        self,
        request_values: Mapping[str, Any] | None = None,
    ) -> Any:
        """Resolve declared request context fields and their configured defaults."""
        try:
            body = self.request_model.model_validate(
                {} if request_values is None else request_values
            ).model_dump()
        except ValidationError as exc:
            names = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
            raise ContextValidationError(f"Invalid request context fields: {names}") from exc

        values: dict[str, Any] = {}
        for name, definition in self.configuration.fields.items():
            source_key = definition.source.rsplit(".", 1)[-1]
            value = body[source_key]
            try:
                values[name] = _freeze(definition.validate_value(value))
            except ValueError as exc:
                raise ContextValidationError(
                    f"Invalid context field '{name}': check its source, type, "
                    "required setting, and allowed_values"
                ) from exc
        return self.schema(**values)

    def validate_prompt(self, prompt: str) -> None:
        """Find misspelled explicit context references during startup."""
        unknown = set(CONTEXT_REFERENCE.findall(prompt)) - self.configuration.fields.keys()
        if unknown:
            raise ValueError(f"Prompt references unknown context fields: {sorted(unknown)}")


def render_context_prompt(prompt: str, context: Any) -> str:
    """Substitute only explicit context placeholders, preserving other JSON braces."""

    def replace(match: re.Match[str]) -> str:
        value = getattr(context, match.group(1))
        return value if isinstance(value, str) else json.dumps(_thaw(value))

    return CONTEXT_REFERENCE.sub(replace, prompt)


def _freeze(value: Any) -> Any:
    """Prevent mutation of nested objects as well as top-level attributes."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Convert immutable JSON containers for explicit prompt rendering."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
