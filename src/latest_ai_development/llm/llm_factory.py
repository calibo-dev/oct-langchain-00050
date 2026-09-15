from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from latest_ai_development.config.settings import get_settings, normalize_provider_name

load_dotenv()

SUPPORTED_PROVIDERS = ("OpenAI", "AnthropicAI", "GeminiAI", "BedrockAI", "Ollama")


def resolve_api_key(
    secret_name: str,
) -> str:
    """
    Resolve a provider API key from its provider-specific secret name.
    """
    secret_name = secret_name.strip()

    if not secret_name:
        return ""

    from latest_ai_development.secrets_manager import SecretsManager

    return (SecretsManager().get_secret(secret_name) or "").strip()


def get_llm(model_config: dict[str, Any], section: str = "primary"):
    """Create one LLM from a stage-level model section.

    `model_config` is expected to come from `stages.yaml`:

        model:
          primary:
            provider: OpenAI
            modelId: gpt-4.1-mini
            generationDefaults: {}
          fallback:
            provider: OpenAI
            modelId: gpt-4.1-nano
            generationDefaults: {}
    """

    section_config = _get_model_section(model_config, section)
    raw_provider = _required_string(section_config, "provider", f"model.{section}.provider")
    provider = normalize_provider_name(raw_provider)
    model_name = _required_string(section_config, "modelId", f"model.{section}.modelId")
    generation_defaults = section_config.get("generationDefaults") or {}
    if not isinstance(generation_defaults, dict):
        raise ValueError(f"model.{section}.generationDefaults must be a mapping when provided")

    settings = get_settings()

    if provider == "openai":

        api_key = resolve_api_key(getattr(settings, "openai_api_key_secret", ""))

        if not api_key:
            raise ValueError(
                "OpenAI API key not found. "
                "Set OPENAI_API_KEY_SECRET."
            )

        return ChatOpenAI(
            **_openai_kwargs(model_name, generation_defaults),
            api_key=api_key,
        )

    if provider == "anthropicai":

        api_key = resolve_api_key(getattr(settings, "anthropicai_api_key_secret", ""))

        if not api_key:
            raise ValueError(
                "Anthropic API key not found. "
                "Set ANTHROPICAI_API_KEY_SECRET."
            )

        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise ImportError(
                "Anthropic provider requires the 'langchain-anthropic' package. "
                "Run `uv sync` to install template dependencies."
            ) from exc

        return ChatAnthropic(
            **_anthropic_kwargs(model_name, generation_defaults),
            api_key=api_key,
        )

    if provider == "geminiai":

        api_key = resolve_api_key(getattr(settings, "geminiai_api_key_secret", ""))

        if not api_key:
            raise ValueError(
                "Gemini API key not found. "
                "Set GEMINIAI_API_KEY_SECRET."
            )

        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise ImportError(
                "Gemini provider requires the 'langchain-google-genai' package. "
                "Run `uv sync` to install template dependencies."
            ) from exc

        return ChatGoogleGenerativeAI(
            **_gemini_kwargs(model_name, generation_defaults),
            api_key=api_key,
        )

    if provider == "bedrockai":

        api_key = resolve_api_key(getattr(settings, "bedrockai_api_key_secret", ""))

        if not api_key:
            raise ValueError(
                "BedrockAI API key not found. "
                "Set BEDROCK_AI_API_KEY_SECRET."
            )
        try:
            from langchain_aws import ChatBedrockConverse
        except ImportError as exc:
            raise ImportError(
                "AWS Bedrock provider requires the 'langchain-aws' package. "
                "Run `uv sync` to install template dependencies."
            ) from exc

        return ChatBedrockConverse(
            **_bedrock_kwargs(model_name, generation_defaults),
            api_key=api_key,
        )

    if provider == "ollama":

        return ChatOllama(
            **_ollama_kwargs(model_name, generation_defaults),
            base_url=settings.ollama_base_url,
        )

    raise ValueError(
        f"Unsupported provider '{raw_provider}'. Expected one of: {', '.join(SUPPORTED_PROVIDERS)}"
    )


def get_llm_candidates(model_config: dict[str, Any]) -> list[Any]:
    """Return primary plus optional fallback LLMs for a stage."""
    candidates = [get_llm(model_config, section="primary")]

    candidates.extend(get_fallback_llms(model_config))

    return candidates


def get_fallback_llms(model_config: dict[str, Any]) -> list[Any]:
    """Return configured fallback LLMs without the primary model."""
    fallback_config = model_config.get("fallback") if isinstance(model_config, dict) else None
    if not fallback_config:
        return []

    if not isinstance(fallback_config, dict):
        raise ValueError("model.fallback must be a mapping when provided")

    return [get_llm(model_config, section="fallback")]


def _get_model_section(model_config: dict[str, Any], section: str) -> dict[str, Any]:
    if not isinstance(model_config, dict):
        raise ValueError("stages.yaml stage model config must be a mapping")

    section_config = model_config.get(section)
    if not isinstance(section_config, dict):
        raise ValueError(f"stages.yaml stage must define model.{section}")

    return section_config


def _required_string(config: dict[str, Any], key: str, label: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"stages.yaml stage must define {label}")
    return value.strip()


def _apply_common_generation_defaults(kwargs: dict[str, Any], defaults: dict[str, Any]) -> None:
    if "temperature" in defaults:
        kwargs["temperature"] = defaults["temperature"]
    if "topP" in defaults:
        kwargs["top_p"] = defaults["topP"]


def _openai_kwargs(model_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    if model_name.lower().startswith("gpt-5"):
        return _openai_kwargs_gpt_5(model_name, defaults)

    return _openai_kwargs_non_gpt_5(model_name, defaults)


def _openai_kwargs_gpt_5(model_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    """Build GPT-5 arguments without unsupported sampling and penalty parameters."""
    kwargs: dict[str, Any] = {"model": model_name}

    if "maxOutputTokens" in defaults:
        kwargs["max_completion_tokens"] = defaults["maxOutputTokens"]

    response_format = defaults.get("responseFormat")
    if isinstance(response_format, dict):
        kwargs["model_kwargs"] = {"response_format": response_format}

    return kwargs


def _openai_kwargs_non_gpt_5(model_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model_name}
    _apply_common_generation_defaults(kwargs, defaults)

    if "maxOutputTokens" in defaults:
        kwargs["max_tokens"] = defaults["maxOutputTokens"]
    if "presencePenalty" in defaults:
        kwargs["presence_penalty"] = defaults["presencePenalty"]
    if "frequencyPenalty" in defaults:
        kwargs["frequency_penalty"] = defaults["frequencyPenalty"]

    response_format = defaults.get("responseFormat")
    if isinstance(response_format, dict):
        kwargs["model_kwargs"] = {"response_format": response_format}

    return kwargs


def _anthropic_kwargs(model_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model_name}
    _apply_common_generation_defaults(kwargs, defaults)
    if "maxOutputTokens" in defaults:
        kwargs["max_tokens"] = defaults["maxOutputTokens"]
    return kwargs


def _gemini_kwargs(model_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model_name}
    _apply_common_generation_defaults(kwargs, defaults)
    if "maxOutputTokens" in defaults:
        kwargs["max_output_tokens"] = defaults["maxOutputTokens"]
    return kwargs

def _bedrock_kwargs(model_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model_name}
    _apply_common_generation_defaults(kwargs, defaults)
    if "maxOutputTokens" in defaults:
        kwargs["max_tokens"] = defaults["maxOutputTokens"]

    additional_model_request_fields = defaults.get("additionalModelRequestFields")
    if isinstance(additional_model_request_fields, dict):
        kwargs["additional_model_request_fields"] = additional_model_request_fields
    return kwargs

def _ollama_kwargs(model_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model_name}
    _apply_common_generation_defaults(kwargs, defaults)
    if "maxOutputTokens" in defaults:
        kwargs["num_predict"] = defaults["maxOutputTokens"]
    return kwargs
