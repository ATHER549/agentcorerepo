import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from app.providers.base import BaseProvider, register_provider

logger = logging.getLogger(__name__)

# Anthropic doesn't have a public list-models API; maintain a static list.
_ANTHROPIC_MODELS = [
    "claude-opus-4-20250514",
    "claude-sonnet-4-20250514",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
]


@register_provider("anthropic")
class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider (native). Does not support embeddings."""

    async def list_models(self, provider_config: dict[str, Any]) -> list[str]:
        return list(_ANTHROPIC_MODELS)

    def build_model(
        self,
        model: str,
        provider_config: dict[str, Any],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        n: int | None = None,
        streaming: bool = False,
        seed: int | None = None,
        json_mode: bool = False,
        model_kwargs: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        api_key = provider_config.get("api_key", "")
        base_url = provider_config.get("base_url")

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "streaming": streaming,
            # Anthropic requires max_tokens — default to 4096 if not set
            "max_tokens": max_tokens or 4096,
        }

        if base_url:
            kwargs["base_url"] = base_url
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if top_k is not None:
            kwargs["top_k"] = top_k
        if model_kwargs:
            kwargs["model_kwargs"] = model_kwargs

        return ChatAnthropic(**kwargs)
