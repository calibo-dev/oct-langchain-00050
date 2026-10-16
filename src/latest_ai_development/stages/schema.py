"""Pydantic models for the values stored in config/stages.yaml."""

from __future__ import annotations

import keyword
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ExecutionMode = Literal["sequential", "parallel"]


class StageDefinition(BaseModel):
    """One step in the configured workflow."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    execution: ExecutionMode
    depends_on: list[str] = Field(default_factory=list)
    agents: list[str] = Field(min_length=1)
    inputs: list[str] = Field()
    outputs: list[str] = Field(min_length=1)

    @field_validator("depends_on", "agents", "inputs", "outputs")
    @classmethod
    def validate_names(cls, names: list[str]) -> list[str]:
        """Reject empty names and duplicate references in one stage."""
        seen_names: set[str] = set()
        for name in names:
            if not name.strip():
                raise ValueError("names must not be empty")
            if name in seen_names:
                raise ValueError("names must be unique")
            seen_names.add(name)
        return names


class WorkflowDefinition(BaseModel):
    """The top-level workflow object in stages.yaml."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    execution: ExecutionMode
    inputs: list[str]
    stages: list[StageDefinition] = Field(min_length=1)

    @field_validator("inputs")
    @classmethod
    def validate_inputs(cls, names: list[str]) -> list[str]:
        """Reject empty or duplicate workflow-level input names."""
        seen_names: set[str] = set()
        for name in names:
            if (
                not name.isidentifier()
                or keyword.iskeyword(name)
                or name.startswith("_")
                or name.startswith("model_")
                or hasattr(BaseModel, name)
            ):
                raise ValueError(
                    f"Invalid workflow input '{name}': use a public Python identifier "
                    "that does not conflict with Pydantic model attributes"
                )
            if name in seen_names:
                raise ValueError("workflow inputs must be unique")
            seen_names.add(name)
        return names

    @model_validator(mode="after")
    def validate_unique_stage_names(self) -> Self:
        """Stage names become dependency keys, so each name must be unique."""
        seen_names: set[str] = set()
        for stage in self.stages:
            if stage.name in seen_names:
                raise ValueError("stage names must be unique")
            seen_names.add(stage.name)
        return self
