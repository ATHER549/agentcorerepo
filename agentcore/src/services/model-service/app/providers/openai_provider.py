import logging
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.providers.base import BaseProvider, register_provider

logger = logging.getLogger(__name__)


@register_provider("openai")
class OpenAIProvider(BaseProvider):
    """OpenAI provider (native)."""

    async def list_models(self, provider_config: dict[str, Any]) -> list[str]:
        api_key = provider_config.get("api_key", "")
        base_url = provider_config.get("base_url", "https://api.openai.com/v1")
        if not api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
                data = response.json()
                return sorted(
                    [m["id"] for m in data.get("data", []) if "gpt" in m.get("id", "").lower()],
                    reverse=True,
                )
        except Exception as e:
            logger.warning("Failed to list OpenAI models: %s", e)
            return []

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
        organization = provider_config.get("organization")

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "streaming": streaming,
            "stream_usage": True,
        }

        if base_url:
            kwargs["base_url"] = base_url
        if organization:
            kwargs["organization"] = organization
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if seed is not None:
            kwargs["seed"] = seed
        if model_kwargs:
            kwargs["model_kwargs"] = model_kwargs

        llm = ChatOpenAI(**kwargs)

        if json_mode:
            llm = llm.bind(response_format={"type": "json_object"})

        return llm

    def build_embeddings(
        self,
        model: str,
        provider_config: dict[str, Any],
        *,
        dimensions: int | None = None,
    ) -> OpenAIEmbeddings:
        api_key = provider_config.get("api_key", "")
        base_url = provider_config.get("base_url")

        kwargs: dict[str, Any] = {"model": model, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if dimensions:
            kwargs["dimensions"] = dimensions
        return OpenAIEmbeddings(**kwargs)
