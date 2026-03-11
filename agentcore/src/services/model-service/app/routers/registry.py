"""REST endpoints for the model registry."""

from __future__ import annotations

import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.database import get_session
from app.models.registry import (
    ModelRegistryCreate,
    ModelRegistryRead,
    ModelRegistryUpdate,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.providers.base import get_provider
from app.services import registry_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/registry", tags=["registry"])
# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/models", response_model=list[ModelRegistryRead])
async def list_registry_models(
    provider: str | None = None,
    environment: str | None = None,
    model_type: str | None = None,
    active_only: bool = True,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """List all registered models, optionally filtered by provider, environment, and/or model type."""
    return await registry_service.get_models(
        session, provider=provider, environment=environment, model_type=model_type, active_only=active_only
    )


@router.post("/models", response_model=ModelRegistryRead, status_code=201)
async def create_registry_model(
    body: ModelRegistryCreate,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Register a new model."""
    return await registry_service.create_model(session, body)


@router.get("/models/{model_id}", response_model=ModelRegistryRead)
async def get_registry_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Get a single registered model by ID."""
    model = await registry_service.get_model(session, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.put("/models/{model_id}", response_model=ModelRegistryRead)
async def update_registry_model(
    model_id: UUID,
    body: ModelRegistryUpdate,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Update an existing registered model."""
    model = await registry_service.update_model(session, model_id, body)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.delete("/models/{model_id}", status_code=204)
async def delete_registry_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Delete a registered model."""
    deleted = await registry_service.delete_model(session, model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model not found")


@router.get("/models/{model_id}/config")
async def get_model_decrypted_config(
    model_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Return the full model config with decrypted API key.  Internal use only."""
    config = await registry_service.get_decrypted_config(session, model_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return config


# ---------------------------------------------------------------------------
# Test connection - LLM
# ---------------------------------------------------------------------------


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_model_connection(
    body: TestConnectionRequest,
    _api_key: str = Depends(verify_api_key),
):
    """Build the provider, send a simple message, and report success/failure."""
    try:
        provider = get_provider(body.provider)
        provider_config: dict = body.provider_config or {}
        if body.api_key:
            provider_config["api_key"] = body.api_key
        if body.base_url:
            provider_config["base_url"] = body.base_url
            if body.provider == "azure":
                provider_config.setdefault("azure_endpoint", body.base_url)

        model = provider.build_model(
            model=body.model_name,
            provider_config=provider_config,
            max_tokens=50,
            streaming=False,
        )
        messages = provider.build_messages([{"role": "user", "content": "Hello"}])

        start = time.perf_counter()
        ai_message = await provider.invoke(model, messages)
        latency_ms = (time.perf_counter() - start) * 1000

        content = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        return TestConnectionResponse(
            success=True,
            message=f"Model responded: {content[:100]}",
            latency_ms=round(latency_ms, 1),
        )
    except Exception as e:
        logger.warning("Test connection failed for %s/%s: %s", body.provider, body.model_name, e)
        return TestConnectionResponse(success=False, message=str(e))


# ---------------------------------------------------------------------------
# Test connection - Embeddings
# ---------------------------------------------------------------------------


@router.post("/test-embedding-connection", response_model=TestConnectionResponse)
async def test_embedding_connection(
    body: TestConnectionRequest,
    _api_key: str = Depends(verify_api_key),
):
    """Build an embedding provider, embed a test string, and report success/failure + latency."""
    try:
        provider = get_provider(body.provider)
        provider_config: dict = body.provider_config or {}
        if body.api_key:
            provider_config["api_key"] = body.api_key
        if body.base_url:
            provider_config["base_url"] = body.base_url
            if body.provider == "azure":
                provider_config.setdefault("azure_endpoint", body.base_url)

        embeddings = provider.build_embeddings(
            model=body.model_name,
            provider_config=provider_config,
        )

        start = time.perf_counter()
        result = await embeddings.aembed_query("Hello")
        latency_ms = (time.perf_counter() - start) * 1000

        dim = len(result) if result else 0
        return TestConnectionResponse(
            success=True,
            message=f"Embedding generated: {dim} dimensions",
            latency_ms=round(latency_ms, 1),
        )
    except NotImplementedError as e:
        return TestConnectionResponse(success=False, message=str(e))
    except Exception as e:
        logger.warning("Test embedding connection failed for %s/%s: %s", body.provider, body.model_name, e)
        return TestConnectionResponse(success=False, message=str(e))
