"""Embedding generation service."""

import logging
from uuid import UUID

from app.providers.base import get_provider
from app.schemas import (
    EmbeddingData,
    EmbeddingRequest,
    EmbeddingResponse,
    UsageInfo,
)

logger = logging.getLogger(__name__)


async def _resolve_registry_config(request: EmbeddingRequest) -> EmbeddingRequest:
    """If the request references a registry model, resolve the full config from DB."""
    registry_model_id = request.provider_config.get("registry_model_id")
    if not registry_model_id:
        return request

    from app.database import get_session
    from app.services.registry_service import get_decrypted_config

    async for session in get_session():
        config = await get_decrypted_config(session, UUID(str(registry_model_id)))

    if config is None:
        msg = f"Registry model {registry_model_id} not found"
        raise ValueError(msg)

    # Build merged provider_config from registry data
    provider_config = dict(config.get("provider_config", {}))
    provider_config["api_key"] = config["api_key"]
    if config.get("base_url"):
        provider_config["base_url"] = config["base_url"]
        if config["provider"] == "azure":
            provider_config.setdefault("azure_endpoint", config["base_url"])

    defaults = config.get("default_params", {})

    return EmbeddingRequest(
        provider=config["provider"],
        model=config["model_name"],
        input=request.input,
        provider_config=provider_config,
        dimensions=request.dimensions if request.dimensions is not None else defaults.get("dimensions"),
    )


async def embed(request: EmbeddingRequest) -> EmbeddingResponse:
    """Generate embeddings for the input texts."""
    request = await _resolve_registry_config(request)
    provider = get_provider(request.provider.value)

    embeddings_model = provider.build_embeddings(
        model=request.model,
        provider_config=request.provider_config,
        dimensions=request.dimensions,
    )

    # Generate embeddings
    vectors = await embeddings_model.aembed_documents(request.input)

    data = [
        EmbeddingData(embedding=vec, index=i)
        for i, vec in enumerate(vectors)
    ]

    # Estimate token usage (approximate — most providers don't return exact counts for embeddings)
    total_chars = sum(len(t) for t in request.input)
    estimated_tokens = total_chars // 4  # rough estimate

    return EmbeddingResponse(
        data=data,
        model=request.model,
        usage=UsageInfo(
            prompt_tokens=estimated_tokens,
            completion_tokens=0,
            total_tokens=estimated_tokens,
        ),
    )
