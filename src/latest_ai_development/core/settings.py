"""Load environment settings and shared YAML configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file is inside src/latest_ai_development/core. Moving up four levels gives
# us the project root, regardless of the directory used to start the app.
BASE_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = BASE_DIR / "src" / "latest_ai_development" / "config"


class Settings(BaseSettings):
    """Required environment variables used by the application."""

    # Application
    app_name: str = Field(alias="APP_NAME")
    app_env: str = Field(alias="APP_ENV")

    # API server
    api_host: str = Field(alias="API_HOST")
    port: int = Field(alias="PORT")
    api_root_path: str = Field(alias="API_ROOT_PATH")

    # Runtime and logging
    debug: bool = Field(alias="DEBUG")
    log_level: str = Field(alias="LOG_LEVEL")

    context: str = Field(alias="CONTEXT")

    # Cloud and secret management
    cloud_provider: str = Field(alias="CLOUD_PROVIDER")
    aws_region: str = Field(alias="AWS_REGION")
    azure_key_vault_url: str = Field(alias="AZURE_KEY_VAULT_URL")

    # Model providers
    openai_api_key_secret: str = Field(alias="OPENAI_API_KEY_SECRET")
    anthropicai_api_key_secret: str = Field(alias="ANTHROPICAI_API_KEY_SECRET")
    geminiai_api_key_secret: str = Field(alias="GEMINIAI_API_KEY_SECRET")
    bedrockai_api_key_secret: str = Field(alias="BEDROCK_AI_API_KEY_SECRET")
    # None means unconfigured, not a default server address. The Ollama builder
    # requires a real environment value only when an active model uses Ollama.
    ollama_base_url: str | None = Field(default=None, alias="OLLAMA_BASE_URL")
    # Pydantic checks explicitly passed values, process environment variables,
    # and then the project .env file. No server address is supplied by code.
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Read one YAML file and make sure its top level is a dictionary."""
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    # All application configuration files start with a named YAML mapping.
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML object: {path}")

    return data


def get_settings() -> Settings:
    """Load application settings from the environment."""
    return Settings()
