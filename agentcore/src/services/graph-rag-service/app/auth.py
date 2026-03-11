import hmac
import logging

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

_auth_warning_logged = False


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    global _auth_warning_logged
    if not settings.api_key:
        if not _auth_warning_logged:
            logger.warning("GRAPH_RAG_SERVICE_API_KEY is not set — requests are unauthenticated!")
            _auth_warning_logged = True
        return api_key or ""
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    if not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key
