"""Create and reuse Snowflake connections declared in YAML.

Non-secret connection values live in ``snowflake_connections.yaml``. Each
connection also declares two environment-variable names. One can contain a PAT
directly; the other can contain the name of an AWS Secrets Manager or Azure Key
Vault secret. Exactly one of those environment variables must be populated.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from threading import RLock
from typing import Any

import snowflake.connector

from latest_ai_development.connections.snowflake.schema import (
    SnowflakeConnectionDefinition,
)
from latest_ai_development.core.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


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
            "database": definition.database,
            "schema": definition.schema_name,
            "user": definition.user,
            "authenticator": "programmatic_access_token",
            "token": pat_token,
            **definition.connection_options.as_connector_parameters(),
        }

        if definition.host:
            parameters["host"] = definition.host
        if definition.role:
            parameters["role"] = definition.role
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
