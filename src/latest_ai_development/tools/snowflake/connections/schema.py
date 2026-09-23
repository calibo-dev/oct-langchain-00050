"""Pydantic schemas for reusable Snowflake connection configuration."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SnowflakeAuthentication(BaseModel):
    """Environment-variable names that can provide a Snowflake PAT.

    The YAML file stores environment-variable names, never PAT values. At runtime,
    exactly one referenced variable must have a value:

    * ``directPatToken`` contains the PAT itself.
    * ``secret`` contains a secret-manager name whose value is the PAT.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    direct_pat_token_env: str = Field(alias="directPatToken", min_length=1)
    secret_env: str = Field(alias="secret", min_length=1)

    @field_validator("direct_pat_token_env", "secret_env")
    @classmethod
    def normalize_environment_name(cls, value: str) -> str:
        """Remove accidental surrounding whitespace from environment names."""
        return value.strip()

    @model_validator(mode="after")
    def validate_distinct_environment_names(self) -> Self:
        """The direct token and secret name must not use the same variable."""
        if self.direct_pat_token_env == self.secret_env:
            raise ValueError("directPatToken and secret must reference different variables")
        return self


class SnowflakeConnectionOptions(BaseModel):
    """Optional Snowflake connector settings shared by connection users."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    client_session_keep_alive: bool = Field(default=False, alias="clientSessionKeepAlive")
    login_timeout: int = Field(default=30, alias="loginTimeout", gt=0)
    network_timeout: int = Field(default=60, alias="networkTimeout", gt=0)

    def as_connector_parameters(self) -> dict[str, Any]:
        """Return names accepted by ``snowflake.connector.connect``."""
        return self.model_dump()


class SnowflakeConnectionDefinition(BaseModel):
    """One reusable Snowflake connection declared in connection YAML."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    account: str = Field(min_length=1)
    host: str | None = None
    warehouse: str = Field(min_length=1)
    database: str | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    user: str = Field(min_length=1)
    authentication: SnowflakeAuthentication
    connection_options: SnowflakeConnectionOptions = Field(
        default_factory=SnowflakeConnectionOptions,
        alias="connectionOptions",
    )

    @field_validator("host", "database", "schema_name", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Treat blank optional connection values as missing."""
        if value is None:
            return None
        normalized_value = str(value).strip()
        return normalized_value or None


class SnowflakeConnectionsConfiguration(BaseModel):
    """Top-level object in ``snowflake_connections.yaml``."""

    model_config = ConfigDict(extra="forbid")

    connections: list[SnowflakeConnectionDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_connection_names(self) -> Self:
        """Connection names are lookup keys and therefore must be unique."""
        names = [connection.name for connection in self.connections]
        if len(names) != len(set(names)):
            raise ValueError("Snowflake connection names must be unique")
        return self
