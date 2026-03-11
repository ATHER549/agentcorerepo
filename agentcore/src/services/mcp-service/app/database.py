"""Async database engine and session factory for the MCP microservice."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

_engine = None
_async_session_factory = None


async def init_db(database_url: str) -> None:
    """Initialise the async engine.  Does NOT call create_all — Alembic owns the schema."""
    global _engine, _async_session_factory  # noqa: PLW0603
    _engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    _async_session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    logger.info("Database engine initialised")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async session."""
    if _async_session_factory is None:
        msg = "Database not initialised. Set MCP_SERVICE_DATABASE_URL in .env."
        raise RuntimeError(msg)
    async with _async_session_factory() as session:
        yield session
