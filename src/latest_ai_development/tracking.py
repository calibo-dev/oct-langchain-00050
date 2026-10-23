from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

from latest_ai_development.core.secrets_manager import SecretsManager

load_dotenv()

logger = logging.getLogger(__name__)

_LANGSMITH_INITIALIZED = False


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def get_tracing_backend() -> str:
    """Return the normalized tracing backend name."""
    configured_backend = os.getenv("TRACING_BACKEND")
    if configured_backend is None and _truthy(os.getenv("LANGSMITH_TRACING")):
        value = "LANGSMITH"
    else:
        value = (configured_backend or "NONE").strip().upper() or "NONE"

    if value in {"OFF", "DISABLED"}:
        value = "NONE"

    logger.info("Tracing backend: %s", value)
    return value


def _resolve_langsmith_api_key() -> str | None:
    secret_name = os.getenv("LANGSMITH_API_KEY_SECRET", "").strip()
    if not secret_name:
        return None

    secret_value = SecretsManager().get_secret(secret_name)
    return secret_value.strip() if secret_value else None


def initialize_langsmith_tracing() -> None:
    """Enable LangSmith tracing for LangChain when TRACING_BACKEND=LANGSMITH."""
    global _LANGSMITH_INITIALIZED

    tracing_backend = get_tracing_backend()
    if tracing_backend != "LANGSMITH":
        if tracing_backend == "NONE":
            os.environ["LANGSMITH_TRACING"] = "false"
            os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return

    if _LANGSMITH_INITIALIZED:
        return

    try:
        api_key = _resolve_langsmith_api_key()
        if not api_key:
            raise ValueError(
                "TRACING_BACKEND is LANGSMITH but LANGSMITH_API_KEY_SECRET is not "
                "configured."
            )

        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ.setdefault("LANGCHAIN_API_KEY", api_key)
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"

        logger.info(
            "LangSmith tracing enabled | project=%s",
            os.getenv("LANGSMITH_PROJECT") or "not set",
        )
        _LANGSMITH_INITIALIZED = True
    except Exception as exc:
        os.environ["TRACING_BACKEND"] = "NONE"
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.warning(
            "LangSmith tracing initialization failed; falling back to no tracing | error=%s",
            exc,
        )
