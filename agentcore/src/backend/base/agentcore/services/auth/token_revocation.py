from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

from agentcore.services.cache.redis_client import get_redis_client
from agentcore.services.deps import get_settings_service


def _revocation_key(user_id: UUID) -> str:
    return f"auth:revoked_after:user:{user_id}"

def _redis_auth_security_enabled() -> bool:
    return os.getenv("AUTH_REDIS_SECURITY_KEYS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def revoke_user_tokens(user_id: UUID) -> None:
    if not _redis_auth_security_enabled():
        return
    settings_service = get_settings_service()
    redis = get_redis_client(settings_service)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    await redis.set(_revocation_key(user_id), str(now_ts))


async def is_user_token_revoked(user_id: UUID, token_iat: int | None) -> bool:
    if not _redis_auth_security_enabled():
        return False
    settings_service = get_settings_service()
    redis = get_redis_client(settings_service)
    revoked_after = await redis.get(_revocation_key(user_id))
    if not revoked_after:
        return False
    revoked_after_ts = int(revoked_after)
    token_iat_ts = int(token_iat or 0)
    return token_iat_ts <= revoked_after_ts
