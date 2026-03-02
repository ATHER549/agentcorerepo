from typing import Optional
import json
import redis.asyncio as redis

from agentcore.services.database.models.user.model import User
from agentcore.services.settings.service import SettingsService
from .redis_client import get_redis_client
import json

class UserCacheService:
    def __init__(self, settings_service):
        self.redis = get_redis_client(settings_service)
        self.ttl = settings_service.settings.redis_cache_expire

    async def get_user(self, user_id: str):
        data = await self.redis.get(f"user:{user_id}")
        return json.loads(data) if data else None

    async def set_user(self, user_dict: dict):
        key = f"user:{user_dict['id']}"
        await self.redis.setex(
            key,
            self.ttl,
            json.dumps(user_dict),
        )

    async def delete_user(self, user_id: str):
        await self.redis.delete(f"user:{user_id}")
