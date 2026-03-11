import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.database import get_session
from app.providers.base import get_provider
from app.schemas import ModelInfo, ModelListRequest, ModelListResponse, ProviderModelListResponse
from app.services import registry_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """List available models from the registry."""
    try:
        models = await registry_service.get_models(session, active_only=True)
        data = [
            ModelInfo(id=m.model_name, owned_by=m.provider, provider=m.provider)
            for m in models
        ]
        return ModelListResponse(data=data)
    except Exception as e:
        logger.warning("Failed to list models from registry: %s", e)
        return ModelListResponse(data=[])


@router.post("/models/list", response_model=ProviderModelListResponse)
async def list_provider_models(
    request: ModelListRequest,
    _api_key: str = Depends(verify_api_key),
):
    """Fetch live model list from a specific provider using the provider's API key."""
    try:
        provider = get_provider(request.provider.value)
        models = await provider.list_models(request.provider_config)
        return ProviderModelListResponse(models=models)
    except Exception as e:
        logger.warning("Failed to list models for provider %s: %s", request.provider, e)
        return ProviderModelListResponse(models=[])
