"""Pydantic models for the values stored in config/agents.yaml."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgentModel(BaseModel):
    """One LLM option for an agent."""

    # Reject unknown YAML fields so spelling mistakes are found during startup.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    provider: str = Field(min_length=1)
    # YAML uses modelId, while Python code uses the standard snake_case name.
    model_id: str = Field(alias="modelId", min_length=1)


class AgentDefinition(BaseModel):
    """Everything needed to create and run one configured agent."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    model: list[AgentModel] = Field(min_length=1)
    inputs: list[str] = Field()
    outputs: list[str] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    # None means optional tool use; {} requires it on every invocation.
    # Otherwise every configured input/value pair must match to require a call.
    required_tool_when: dict[str, str] | None = None
    system_prompt: str = Field(min_length=1)

    @property
    def primary_model(self) -> AgentModel:
        """The first model in YAML is the agent's preferred model."""
        return self.model[0]

    @model_validator(mode="after")
    def validate_tool_requirement(self) -> AgentDefinition:
        """Reject tool requirements that cannot be satisfied by this agent."""
        if self.required_tool_when is not None:
            if not self.tools:
                raise ValueError("required_tool_when requires at least one configured tool")
            unknown = set(self.required_tool_when) - set(self.inputs)
            if unknown:
                raise ValueError(f"required_tool_when references unknown inputs: {sorted(unknown)}")
        return self

    @field_validator("inputs", "outputs", "tools")
    @classmethod
    def validate_field_names(cls, field_names: list[str]) -> list[str]:
        """Reject empty or repeated names."""
        seen_names: set[str] = set()

        for field_name in field_names:
            if not field_name.strip():
                raise ValueError("field names must not be empty")
            if field_name in seen_names:
                raise ValueError(f"field name '{field_name}' must be unique")
            seen_names.add(field_name)

        return field_names

    @field_validator("model")
    @classmethod
    def validate_unique_models(cls, models: list[AgentModel]) -> list[AgentModel]:
        """Avoid configuring the same model twice for one agent."""
        seen_models: set[tuple[str, str]] = set()

        for model in models:
            model_key = (model.provider.strip().lower(), model.model_id.strip())
            if model_key in seen_models:
                raise ValueError(f"agent model '{model.provider}/{model.model_id}' must be unique")
            seen_models.add(model_key)

        return models


class AgentsConfiguration(BaseModel):
    """The top-level object in agents.yaml."""

    model_config = ConfigDict(extra="forbid")

    agents: list[AgentDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_agent_names(self) -> AgentsConfiguration:
        """Agent names become registry keys, so each name must be unique."""
        seen_names: set[str] = set()
        for agent in self.agents:
            if agent.name in seen_names:
                raise ValueError("agent names must be unique")
            seen_names.add(agent.name)
        return self
