from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

from app.providers.base import BaseProvider, register_provider


@register_provider("azure")
class AzureOpenAIProvider(BaseProvider):
    """Azure OpenAI provider."""

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
        azure_endpoint = provider_config.get("azure_endpoint", "")
        azure_deployment = provider_config.get("azure_deployment", model)
        api_version = provider_config.get("api_version", "2025-10-01-preview")

        kwargs: dict[str, Any] = {
            "azure_endpoint": azure_endpoint,
            "azure_deployment": azure_deployment,
            "api_version": api_version,
            "api_key": api_key,
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

        llm = AzureChatOpenAI(**kwargs)

        if json_mode:
            llm = llm.bind(response_format={"type": "json_object"})

        return llm

    def build_embeddings(
        self,
        model: str,
        provider_config: dict[str, Any],
        *,
        dimensions: int | None = None,
    ) -> AzureOpenAIEmbeddings:
        api_key = provider_config.get("api_key", "")
        azure_endpoint = provider_config.get("azure_endpoint", "")
        azure_deployment = provider_config.get("azure_deployment", model)
        api_version = provider_config.get("api_version", "2025-10-01-preview")

        kwargs: dict[str, Any] = {
            "model": model,
            "azure_endpoint": azure_endpoint,
            "azure_deployment": azure_deployment,
            "api_version": api_version,
            "api_key": api_key,
        }
        if dimensions:
            kwargs["dimensions"] = dimensions
        return AzureOpenAIEmbeddings(**kwargs)
