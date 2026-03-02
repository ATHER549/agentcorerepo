from typing import Optional

import redis.asyncio as redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError

from agentcore.services.settings.service import SettingsService

_redis_client: Optional[redis.StrictRedis] = None
_redis_signature: Optional[tuple] = None

def get_redis_client(settings_service: SettingsService) -> redis.StrictRedis:
    global _redis_client, _redis_signature
    signature = (
        settings_service.settings.redis_host,
        settings_service.settings.redis_port,
        settings_service.settings.redis_db,
        settings_service.settings.redis_password,
        settings_service.settings.redis_ssl,
    )
    if _redis_client is None or _redis_signature != signature:
        _redis_client = redis.StrictRedis(
            host=settings_service.settings.redis_host,
            port=settings_service.settings.redis_port,
            db=settings_service.settings.redis_db,
            password=settings_service.settings.redis_password,
            ssl=settings_service.settings.redis_ssl,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            # Auto-detect stale connections before use
            health_check_interval=15,
            # Retry on transient connection drops (Azure idle timeout, etc.)
            retry=Retry(ExponentialBackoff(cap=2, base=0.1), retries=3),
            retry_on_error=[ConnectionError, TimeoutError, OSError],
        )
        _redis_signature = signature
    return _redis_client
