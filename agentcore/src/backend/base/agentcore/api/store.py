
from fastapi import APIRouter

router = APIRouter(tags=["Store"], prefix="/store")


@router.get("/check/api_key")
async def check_api_key():
    """Check if API key exists - dummy implementation returning OK."""
    return {"has_api_key": False, "is_valid": False}


@router.get("/check/")
async def check_store():
    """Check if store is available - dummy implementation returning OK."""
    return {"enabled": False}


@router.get("/tags")
async def get_store_tags():
    """Return store tags list."""
    return []
