"""Validate, create, and reuse Snowflake connections declared in YAML.

Non-secret connection values live in ``tools_connections.yaml``. Each
connection also declares two environment-variable names. One can contain a PAT
directly; the other can contain the name of an AWS Secrets Manager or Azure Key
Vault secret. Exactly one of those environment variables must be populated.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from threading import RLock
from typing import Any, Literal, Self

import snowflake.connector
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from latest_ai_development.core.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


class SnowflakeAuthentication(BaseModel):
    """Environment-variable names that can provide a Snowflake PAT."""

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
    connector: Literal["snowflake"]
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
    """Snowflake records selected from ``tools_connections.yaml``."""

    model_config = ConfigDict(extra="forbid")

    connections: list[SnowflakeConnectionDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_connection_names(self) -> Self:
        """Connection names are lookup keys and therefore must be unique."""
        names = [connection.name for connection in self.connections]
        if len(names) != len(set(names)):
            raise ValueError("Snowflake connection names must be unique")
        return self


def validate_snowflake_connections_configuration(
    raw_configuration: dict[str, Any],
) -> SnowflakeConnectionsConfiguration:
    """Convert connection YAML into checked Snowflake connection objects."""
    try:
        return SnowflakeConnectionsConfiguration.model_validate(raw_configuration)
    except ValidationError as exc:
        raise ValueError(f"Invalid tools_connections.yaml configuration:\n{exc}") from exc


class SnowflakeConnectionManager:
    """Resolve credentials and cache connections by configured connection name."""

    def __init__(self, definitions: Iterable[SnowflakeConnectionDefinition]) -> None:
        """Create a manager from validated connection definitions."""
        self._definitions = {definition.name: definition for definition in definitions}
        self._connections: dict[str, Any] = {}
        self._lock = RLock()

    def get_definition(self, connection_name: str) -> SnowflakeConnectionDefinition:
        """Return a connection definition by its stable YAML name."""
        try:
            return self._definitions[connection_name]
        except KeyError as exc:
            raise KeyError(f"Snowflake connection '{connection_name}' is not configured") from exc

    def get_connection(self, connection_name: str) -> Any:
        """Return an open cached connection, creating it when first requested."""
        definition = self.get_definition(connection_name)

        # A single manager is shared by every tool. The lock prevents two agents
        # from creating duplicate connections for the same name concurrently.
        with self._lock:
            connection = self._connections.get(connection_name)
            if connection is not None and not connection.is_closed():
                return connection

            connection_parameters = self._build_connection_parameters(definition)
            try:
                connection = snowflake.connector.connect(**connection_parameters)
            except snowflake.connector.errors.DatabaseError as exc:
                raise _friendly_connection_error(definition, exc) from exc

            self._connections[connection_name] = connection
            logger.info("Snowflake connection opened connection=%s", connection_name)
            return connection

    def close(self) -> None:
        """Close every cached Snowflake connection."""
        with self._lock:
            for name in tuple(self._connections):
                connection = self._connections.pop(name, None)
                if connection is not None and not connection.is_closed():
                    connection.close()
                    logger.info("Snowflake connection closed connection=%s", name)

    @staticmethod
    def _build_connection_parameters(
        definition: SnowflakeConnectionDefinition,
    ) -> dict[str, Any]:
        """Translate one definition into Snowflake connector keyword arguments."""
        pat_token = _resolve_pat_token(definition)
        parameters: dict[str, Any] = {
            "account": definition.account,
            "warehouse": definition.warehouse,
            "user": definition.user,
            "authenticator": "programmatic_access_token",
            "token": pat_token,
            **definition.connection_options.as_connector_parameters(),
        }

        if definition.database:
            parameters["database"] = definition.database
        if definition.schema_name:
            parameters["schema"] = definition.schema_name
        if definition.host:
            parameters["host"] = definition.host
        return parameters


def _read_environment_value(variable_name: str) -> str:
    """Return one trimmed environment value without logging sensitive content."""
    return str(os.getenv(variable_name) or "").strip()


def _resolve_pat_token(definition: SnowflakeConnectionDefinition) -> str:
    """Resolve a PAT from exactly one configured environment-variable source."""
    authentication = definition.authentication
    direct_pat = _read_environment_value(authentication.direct_pat_token_env)
    secret_name = _read_environment_value(authentication.secret_env)

    if direct_pat and secret_name:
        raise RuntimeError(
            f"Snowflake connection '{definition.name}' has both PAT sources configured. "
            f"Set only one of {authentication.direct_pat_token_env} or "
            f"{authentication.secret_env}."
        )
    if not direct_pat and not secret_name:
        raise RuntimeError(
            f"Snowflake connection '{definition.name}' requires a PAT. Set exactly one of "
            f"{authentication.direct_pat_token_env} or {authentication.secret_env}."
        )
    if direct_pat:
        return direct_pat

    secret_value = SecretsManager().get_secret(secret_name)
    pat_token = str(secret_value or "").strip()
    if not pat_token:
        raise RuntimeError(
            f"PAT secret '{secret_name}' for Snowflake connection "
            f"'{definition.name}' resolved to an empty value."
        )
    return pat_token


def _friendly_connection_error(
    definition: SnowflakeConnectionDefinition,
    error: Exception,
) -> RuntimeError:
    """Add connection context without exposing a PAT or other secret value."""
    message = str(error)
    if "token" in message.lower() or "expired" in message.lower() or "pat" in message.lower():
        return RuntimeError(
            f"Snowflake PAT for connection '{definition.name}' is invalid or expired."
        )
    return RuntimeError(f"Unable to open Snowflake connection '{definition.name}': {message}")
