from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directories
BASE_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = BASE_DIR / "src" / "latest_ai_development" / "config"

DEFAULT_OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_CONTEXT_DIR = BASE_DIR / "knowledge"

PROVIDER_ALIASES = {
    "anthropic": "anthropicai",
    "gemini": "geminiai",
    "bedrock": "bedrockai",
    "microsoftfoundry": "microsoftfoundryai",
}


def normalize_api_context(raw_context: str | None) -> str:
    """Return a stable URL prefix like '/testing' or ''."""
    if not raw_context:
        return ""

    normalized = raw_context.strip()
    if not normalized or normalized == "/":
        return ""

    return "/" + normalized.strip("/")


def normalize_provider_name(provider: str | None) -> str:
    """Return the canonical provider key used by the LLM factory."""
    provider_key = (provider or "").strip().lower()
    return PROVIDER_ALIASES.get(provider_key, provider_key)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "latest-ai-development"
    app_env: str = Field(default="dev", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # OpenAI
    openai_api_key_secret: str = Field(default="", alias="OPENAI_API_KEY_SECRET")

    # Anthropic
    anthropicai_api_key_secret: str = Field(default="", alias="ANTHROPICAI_API_KEY_SECRET")

    # Gemini
    geminiai_api_key_secret: str = Field(default="", alias="GEMINIAI_API_KEY_SECRET")

    # Bedrock
    bedrock_ai_api_key_secret: str = Field(default="", alias="BEDROCK_AI_API_KEY_SECRET")

    # Microsoft Foundry AI
    microsoft_foundry_ai_endpoint: str = Field(default="", alias="MICROSOFT_FOUNDRY_AI_ENDPOINT")
    microsoft_foundry_ai_api_key_secret: str = Field(default="", alias="MICROSOFT_FOUNDRY_AI_API_KEY_SECRET")

    # Secret Manager
    cloud_provider: str = Field(default="", alias="CLOUD_PROVIDER")
    azure_key_vault_url: str = Field(default="", alias="AZURE_KEY_VAULT_URL")

    # Tracing / Observability
    tracing_backend: str = Field(default="NONE", alias="TRACING_BACKEND")
    langsmith_endpoint: str = Field(default="", alias="LANGSMITH_ENDPOINT")
    langsmith_project: str = Field(default="", alias="LANGSMITH_PROJECT")
    langsmith_api_key_secret: str = Field(default="", alias="LANGSMITH_API_KEY_SECRET")

    # Ollama
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    # API
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_root_path: str = Field(default="", alias="API_ROOT_PATH")
    port: int = Field(default=8080, alias="PORT")

    # AWS
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")

    # Context / Knowledge
    context: str = Field(default="/", alias="CONTEXT")

    # Output
    report_output_file: str = Field(default="report.md", alias="REPORT_OUTPUT_FILE")
    output_dir: str = Field(default=str(DEFAULT_OUTPUT_DIR), alias="OUTPUT_DIR")

    # Path helpers
    @property
    def context_path(self) -> Path:
        return Path(self.context).expanduser()

    @property
    def normalized_api_root_path(self) -> str:
        return normalize_api_context(self.api_root_path or self.context)

    @property
    def output_dir_path(self) -> Path:
        return Path(self.output_dir).expanduser()

    @property
    def report_output_path(self) -> Path:
        return self.output_dir_path / self.report_output_file

    # Config file paths
    @property
    def workflow_config_path(self) -> Path:
        return CONFIG_DIR / "workflow.yaml"

    @property
    def stages_config_path(self) -> Path:
        return CONFIG_DIR / "stages.yaml"


# Runtime helpers
def ensure_runtime_dirs(settings: Settings) -> None:
    # settings.context_path.mkdir(parents=True, exist_ok=True)
    settings.output_dir_path.mkdir(parents=True, exist_ok=True)


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML object: {path}")

    return data


# Public helpers
@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    ensure_runtime_dirs(settings)
    return settings


@lru_cache
def get_workflow_config() -> dict[str, Any]:
    return load_yaml_file(get_settings().workflow_config_path)


@lru_cache
def get_stages_config() -> dict[str, Any]:
    return load_yaml_file(get_settings().stages_config_path)
