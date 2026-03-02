from __future__ import annotations

import os

from agentcore.services.cache.redis_client import get_redis_client
from agentcore.services.deps import get_settings_service


def _email_key(email: str) -> str:
    return f"auth:blocked:email:{email.strip().lower()}"


def _entra_key(entra_object_id: str) -> str:
    return f"auth:blocked:entra:{entra_object_id.strip()}"

def _redis_auth_security_enabled() -> bool:
    return os.getenv("AUTH_REDIS_SECURITY_KEYS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def block_identity(*, email: str | None = None, entra_object_id: str | None = None) -> None:
    if not _redis_auth_security_enabled():
        return
    settings_service = get_settings_service()
    redis = get_redis_client(settings_service)
    if email:
        await redis.set(_email_key(email), "1")
    if entra_object_id:
        await redis.set(_entra_key(entra_object_id), "1")


async def is_identity_blocked(*, email: str | None = None, entra_object_id: str | None = None) -> bool:
    if not _redis_auth_security_enabled():
        return False
    settings_service = get_settings_service()
    redis = get_redis_client(settings_service)
    if email:
        if await redis.get(_email_key(email)):
            return True
    if entra_object_id:
        if await redis.get(_entra_key(entra_object_id)):
            return True
    return False
