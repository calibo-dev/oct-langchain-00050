"""Provider-specific LangChain model builders."""

from __future__ import annotations

from typing import Any

from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from latest_ai_development.core.settings import Settings

SUPPORTED_PROVIDERS = ("OpenAI", "AnthropicAI", "GeminiAI", "BedrockAI", "Ollama")

# models.yaml uses provider-neutral names. LangChain provider classes use slightly
# different names. This mapping tells the app how to translate each provider.
PROVIDER_PARAMETER_NAMES = {
    "openai": {
        "temperature": "temperature",
        "topP": "top_p",
        "maxOutputTokens": "max_tokens",
        "presencePenalty": "presence_penalty",
        "frequencyPenalty": "frequency_penalty",
    },
    "anthropicai": {
        "temperature": "temperature",
        "topP": "top_p",
        "maxOutputTokens": "max_tokens",
    },
    "geminiai": {
        "temperature": "temperature",
        "topP": "top_p",
        "maxOutputTokens": "max_output_tokens",
    },
    "bedrockai": {
        "temperature": "temperature",
        "topP": "top_p",
        "maxOutputTokens": "max_tokens",
        "additionalModelRequestFields": "additional_model_request_fields",
    },
    "ollama": {
        "temperature": "temperature",
        "topP": "top_p",
        "maxOutputTokens": "num_predict",
    },
}


def normalize_provider_key(provider: str) -> str:
    """Normalize provider names so YAML can use readable casing."""
    return provider.strip().lower()


def resolve_api_key(secret_name: str) -> str:
    """Resolve a provider API key from its provider-specific secret name."""
    secret_name = secret_name.strip()
    if not secret_name:
        return ""

    from latest_ai_development.core.secrets_manager import SecretsManager

    return (SecretsManager().get_secret(secret_name) or "").strip()


def build_openai_llm(
    settings: Settings,
    model_name: str,
    parameters: dict[str, Any],
) -> Any:
    """Create an OpenAI chat model."""
    api_key = _resolve_required_api_key(
        settings.openai_api_key_secret,
        "OpenAI",
        "OPENAI_API_KEY_SECRET",
    )
    model_parameters = build_model_parameters("openai", model_name, parameters)
    return ChatOpenAI(**model_parameters, api_key=api_key)


def build_anthropic_llm(
    settings: Settings,
    model_name: str,
    parameters: dict[str, Any],
) -> Any:
    """Create an Anthropic chat model."""
    api_key = _resolve_required_api_key(
        settings.anthropicai_api_key_secret,
        "Anthropic",
        "ANTHROPICAI_API_KEY_SECRET",
    )

    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise ImportError(
            "Anthropic provider requires the 'langchain-anthropic' package. "
            "Run `uv sync` to install template dependencies."
        ) from exc

    model_parameters = build_model_parameters("anthropicai", model_name, parameters)
    return ChatAnthropic(**model_parameters, api_key=api_key)


def build_gemini_llm(
    settings: Settings,
    model_name: str,
    parameters: dict[str, Any],
) -> Any:
    """Create a Google Gemini chat model."""
    api_key = _resolve_required_api_key(
        settings.geminiai_api_key_secret,
        "Gemini",
        "GEMINIAI_API_KEY_SECRET",
    )

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise ImportError(
            "Gemini provider requires the 'langchain-google-genai' package. "
            "Run `uv sync` to install template dependencies."
        ) from exc

    model_parameters = build_model_parameters("geminiai", model_name, parameters)
    return ChatGoogleGenerativeAI(**model_parameters, api_key=api_key)


def build_bedrock_llm(
    settings: Settings,
    model_name: str,
    parameters: dict[str, Any],
) -> Any:
    """Create an AWS Bedrock chat model."""
    api_key = _resolve_required_api_key(
        settings.bedrockai_api_key_secret,
        "BedrockAI",
        "BEDROCK_AI_API_KEY_SECRET",
    )

    try:
        from langchain_aws import ChatBedrockConverse
    except ImportError as exc:
        raise ImportError(
            "AWS Bedrock provider requires the 'langchain-aws' package. "
            "Run `uv sync` to install template dependencies."
        ) from exc

    model_parameters = build_model_parameters("bedrockai", model_name, parameters)
    return ChatBedrockConverse(**model_parameters, api_key=api_key)


def build_ollama_llm(
    settings: Settings,
    model_name: str,
    parameters: dict[str, Any],
) -> Any:
    """Create a local Ollama chat model."""
    model_parameters = build_model_parameters("ollama", model_name, parameters)
    return ChatOllama(**model_parameters, base_url=settings.ollama_base_url)


# create_llm() uses this dictionary to choose the right provider function.
# To add a new provider, create a new build_*_llm function and add it here.
PROVIDER_BUILDERS = {
    "openai": build_openai_llm,
    "anthropicai": build_anthropic_llm,
    "geminiai": build_gemini_llm,
    "bedrockai": build_bedrock_llm,
    "ollama": build_ollama_llm,
}


def build_model_parameters(
    provider_key: str,
    model_name: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Build kwargs for the selected LangChain model class.

    Only values present in models.yaml are added. Unknown parameter names are
    passed through as-is so new provider options can be configured without code
    changes.
    """
    model_parameters: dict[str, Any] = {"model": model_name}
    parameter_name_map = PROVIDER_PARAMETER_NAMES.get(provider_key, {})

    for parameter_name, value in parameters.items():
        if parameter_name == "responseFormat":
            _add_response_format(model_parameters, value)
            continue

        target_name = parameter_name_map.get(parameter_name, parameter_name)
        model_parameters[target_name] = value

    return model_parameters


def _resolve_required_api_key(
    secret_name: str,
    provider_name: str,
    setting_name: str,
) -> str:
    """Return a provider API key or fail with a clear startup error."""
    api_key = resolve_api_key(secret_name)
    if not api_key:
        raise ValueError(f"{provider_name} API key not found. Set {setting_name}.")
    return api_key


def _add_response_format(model_parameters: dict[str, Any], response_format: Any) -> None:
    """Add OpenAI-style response format only when YAML asks for non-text output."""
    if isinstance(response_format, dict):
        model_parameters["model_kwargs"] = {"response_format": response_format}
        return

    if not isinstance(response_format, str):
        return

    normalized_response_format = response_format.strip().lower()
    if normalized_response_format and normalized_response_format != "text":
        model_parameters["model_kwargs"] = {"response_format": {"type": normalized_response_format}}
