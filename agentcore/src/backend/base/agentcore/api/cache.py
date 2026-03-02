"""Cache management API endpoints.
Provides endpoints to inspect and clear Redis/in-memory caches.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from agentcore.services.deps import get_cache_service, get_chat_service, get_settings_service

router = APIRouter(prefix="/cache", tags=["Cache Management"])


class CacheStatusResponse(BaseModel):
    cache_type: str
    redis_connected: bool | None = None
    message: str


class CacheClearResponse(BaseModel):
    success: bool
    message: str
    keys_cleared: list[str] | None = None


@router.get("/status", response_model=CacheStatusResponse)
async def cache_status():
    """Check current cache status and connectivity."""
    settings = get_settings_service().settings
    cache_service = get_cache_service()

    response = CacheStatusResponse(
        cache_type=settings.cache_type,
        message=f"Cache type: {settings.cache_type}",
    )

    if settings.cache_type == "redis":
        try:
            from agentcore.services.cache.base import ExternalAsyncBaseCacheService

            if isinstance(cache_service, ExternalAsyncBaseCacheService):
                connected = await cache_service.is_connected()
                response.redis_connected = connected
                response.message = "Redis connected" if connected else "Redis NOT connected"
            else:
                response.redis_connected = False
                response.message = "Cache type is redis but service is not ExternalAsyncBaseCacheService"
        except Exception as exc:
            logger.warning(f"Error checking Redis connectivity: {exc}")
            response.redis_connected = False
            response.message = f"Redis connection error: {exc}"

    return response


@router.delete("/clear/all", response_model=CacheClearResponse)
async def clear_all_cache():
    """Clear ALL cache entries (graph state, frozen vertices, sessions).
    WARNING: This will evict everything. Running flows may need to be rebuilt.
    """
    try:
        cache_service = get_cache_service()

        from agentcore.services.cache.base import AsyncBaseCacheService

        if isinstance(cache_service, AsyncBaseCacheService):
            await cache_service.clear()
        else:
            cache_service.clear()

        return CacheClearResponse(success=True, message="All cache entries cleared")
    except Exception as exc:
        logger.exception("Error clearing cache")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/clear/graph/{agent_id}", response_model=CacheClearResponse)
async def clear_graph_cache(agent_id: str):
    """Clear cached graph state for a specific agent/flow.
    This forces the graph to be rebuilt from the database on the next run.
    Args:
        agent_id: The agent/flow ID whose cached graph to clear.
    """
    try:
        chat_service = get_chat_service()
        await chat_service.clear_cache(agent_id)
        return CacheClearResponse(
            success=True,
            message=f"Graph cache cleared for agent {agent_id}",
            keys_cleared=[agent_id],
        )
    except Exception as exc:
        logger.exception(f"Error clearing graph cache for {agent_id}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/clear/vertex/{vertex_id}", response_model=CacheClearResponse)
async def clear_vertex_cache(vertex_id: str):
    """Clear cached frozen vertex build result.
    Args:
        vertex_id: The vertex ID whose cached build result to clear.
    """
    try:
        chat_service = get_chat_service()
        await chat_service.clear_cache(vertex_id)
        return CacheClearResponse(
            success=True,
            message=f"Vertex cache cleared for {vertex_id}",
            keys_cleared=[vertex_id],
        )
    except Exception as exc:
        logger.exception(f"Error clearing vertex cache for {vertex_id}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/clear/user/{user_id}", response_model=CacheClearResponse)
async def clear_user_cache(user_id: str):
    """Clear cached user data from Redis.
    Args:
        user_id: The user ID whose cached data to clear.
    """
    try:
        settings_service = get_settings_service()
        from agentcore.services.cache.redis_client import get_redis_client

        redis_client = get_redis_client(settings_service)
        key = f"user:{user_id}"
        await redis_client.delete(key)
        return CacheClearResponse(
            success=True,
            message=f"User cache cleared for {user_id}",
            keys_cleared=[key],
        )
    except Exception as exc:
        logger.exception(f"Error clearing user cache for {user_id}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/clear/permissions", response_model=CacheClearResponse)
async def clear_permission_cache(
    role: str | None = Query(None, description="Specific role to clear. If omitted, clears all role caches."),
):
    """Clear cached role permissions from Redis.
    Args:
        role: Optional role name. If provided, only that role's cache is cleared.
              If omitted, all role caches (admin, manager, developer, viewer) are cleared.
    """
    try:
        settings_service = get_settings_service()
        from agentcore.services.cache.redis_client import get_redis_client

        redis_client = get_redis_client(settings_service)
        keys_cleared = []

        if role:
            key = f"role:{role.lower()}"
            await redis_client.delete(key)
            keys_cleared.append(key)
        else:
            for role_name in ["admin", "manager", "developer", "viewer"]:
                key = f"role:{role_name}"
                await redis_client.delete(key)
                keys_cleared.append(key)

        return CacheClearResponse(
            success=True,
            message="Permission cache cleared",
            keys_cleared=keys_cleared,
        )
    except Exception as exc:
        logger.exception("Error clearing permission cache")
        raise HTTPException(status_code=500, detail=str(exc)) from exc