from __future__ import annotations

from uuid import UUID

from agentcore.services.auth.identity_blocklist import block_identity
from agentcore.services.auth.token_revocation import revoke_user_tokens
from agentcore.services.cache.user_cache import UserCacheService
from agentcore.services.deps import get_settings_service


async def invalidate_user_auth(
    user_id: UUID,
    *,
    email: str | None = None,
    entra_object_id: str | None = None,
) -> None:
    settings_service = get_settings_service()
    user_cache = UserCacheService(settings_service)
    await revoke_user_tokens(user_id)
    await block_identity(email=email, entra_object_id=entra_object_id)
    await user_cache.delete_user(str(user_id))
