"""Validate environment settings required to start the application."""

from __future__ import annotations

import logging

from latest_ai_development.core.settings import Settings

logger = logging.getLogger(__name__)

SUPPORTED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def validate_settings_configuration(settings: Settings) -> None:
    """Run all environment-setting checks and report every error together."""
    logger.debug("Application configuration validation started")
    errors: list[str] = []

    # Context is part of the runtime contract, even for workflows without retrieval.
    if not settings.context.strip():
        errors.append("CONTEXT must not be empty")

    # Secret-manager configuration depends on the selected cloud provider.
    if settings.cloud_provider not in {"AWS", "AZURE"}:
        errors.append(
            f"CLOUD_PROVIDER must be 'AWS' or 'AZURE'; received '{settings.cloud_provider}'"
        )
    elif settings.cloud_provider == "AWS" and not settings.aws_region.strip():
        errors.append("AWS_REGION is required when CLOUD_PROVIDER is 'AWS'")
    elif settings.cloud_provider == "AZURE" and not settings.azure_key_vault_url.strip():
        errors.append("AZURE_KEY_VAULT_URL is required when CLOUD_PROVIDER is 'AZURE'")

    # FastAPI accepts an empty root path or a path such as /testing. A single
    # slash and trailing slashes create ambiguous duplicate routes.
    if settings.api_root_path:
        if not settings.api_root_path.startswith("/"):
            errors.append(f"API_ROOT_PATH must start with '/'; received '{settings.api_root_path}'")
        elif settings.api_root_path == "/":
            errors.append("API_ROOT_PATH must be empty or a named path, not '/'")
        elif settings.api_root_path.endswith("/"):
            errors.append(
                f"API_ROOT_PATH must not end with '/'; received '{settings.api_root_path}'"
            )

    # Ports outside the TCP range cannot be bound by the API server.
    if not 1 <= settings.port <= 65535:
        errors.append(f"PORT must be between 1 and 65535; received {settings.port}")

    # An empty host prevents Uvicorn from starting its listener.
    if not settings.api_host.strip():
        errors.append("API_HOST must not be empty")

    # Restrict logging values to levels supported by Python's logging module.
    normalized_log_level = settings.log_level.strip().upper()
    if normalized_log_level not in SUPPORTED_LOG_LEVELS:
        errors.append(
            "LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, or CRITICAL; "
            f"received '{settings.log_level}'"
        )

    if errors:
        details = "\n- ".join(errors)
        logger.error("Application configuration validation failed: %s", details)
        raise ValueError(f"Invalid application configuration:\n- {details}")

    logger.debug("Application configuration validation completed")
