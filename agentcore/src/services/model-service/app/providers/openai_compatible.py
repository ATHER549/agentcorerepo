import logging
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.providers.base import BaseProvider, register_provider

logger = logging.getLogger(__name__)


@register_provider("openai_compatible")
class OpenAICompatibleProvider(BaseProvider):
    """OpenAI-compatible provider (Tier 2).

    Works with any provider that exposes an OpenAI-compatible chat completions API:
    Ollama, DeepSeek, Together, Fireworks, Mistral, vLLM, NVIDIA NIM, OpenRouter, etc.
    """

    async def list_models(self, provider_config: dict[str, Any]) -> list[str]:
        api_key = provider_config.get("api_key", "")
        base_url = provider_config.get("base_url", "")
        if not base_url:
            return []
        try:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            custom_headers = provider_config.get("custom_headers", {})
            if custom_headers:
                headers.update(custom_headers)

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                return sorted([m["id"] for m in data.get("data", [])])
        except Exception as e:
            logger.warning("Failed to list models from %s: %s", base_url, e)
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
        base_url = provider_config.get("base_url", "")

        if not base_url:
            msg = "base_url is required for openai_compatible provider"
            raise ValueError(msg)

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key or "not-needed",
            "base_url": base_url,
            "streaming": streaming,
            "stream_usage": True,
        }

        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if seed is not None:
            kwargs["seed"] = seed
        if model_kwargs:
            kwargs["model_kwargs"] = model_kwargs

        custom_headers = provider_config.get("custom_headers")
        if custom_headers:
            kwargs["default_headers"] = custom_headers

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
        base_url = provider_config.get("base_url", "")

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key or "not-needed",
        }
        if base_url:
            kwargs["base_url"] = base_url
        if dimensions:
            kwargs["dimensions"] = dimensions
        custom_headers = provider_config.get("custom_headers", {})
        if custom_headers:
            kwargs["default_headers"] = custom_headers
        return OpenAIEmbeddings(**kwargs)
