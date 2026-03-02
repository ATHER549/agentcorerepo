
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from agentcore.api.utils import CurrentActiveUser
from agentcore.api.v1_schemas import ApiKeyCreateRequest, ApiKeysResponse


router = APIRouter(tags=["APIKey"], prefix="/api_key")


@router.get("/")
async def get_api_keys(
    current_user: CurrentActiveUser,
) -> ApiKeysResponse:
    """Get all API keys for current user - returns empty list (dummy implementation)."""
    # Azure Key Vault
    return ApiKeysResponse(total_count=0, user_id=current_user.id, api_keys=[])


@router.post("/")
async def create_api_key(
    current_user: CurrentActiveUser,
):
    """Create a new API key - dummy implementation."""
    # Azure Key Vault
    return {"detail": "API Key creation is currently disabled. Will be migrated to Azure Key Vault."}


@router.delete("/{api_key_id}")
async def delete_api_key(
    api_key_id: UUID,
):
    """Delete an API key - dummy implementation."""
    # Azure Key Vault
    return {"detail": "API Key deletion is currently disabled. Will use Azure Key Vault."}


@router.post("/store")
async def save_api_key(
    api_key_request: ApiKeyCreateRequest,
    response: Response,
    current_user: CurrentActiveUser,
):
    """Store API key - dummy implementation."""
    # USe Azure Key Vault
    return {"detail": "API Key storage is currently disabled. Will use Azure Key Vault."}
