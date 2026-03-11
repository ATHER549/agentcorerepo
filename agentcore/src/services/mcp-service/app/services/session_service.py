"""Singleton session manager and client pool for MCP connections."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.mcp_clients.session_manager import MCPSessionManager, cleanup_all_mcp_sessions
from app.mcp_clients.stdio_client import MCPStdioClient
from app.mcp_clients.sse_client import MCPSseClient

logger = logging.getLogger(__name__)

_session_manager: MCPSessionManager | None = None


def get_session_manager() -> MCPSessionManager:
    """Return a lazy singleton MCPSessionManager, configured from settings."""
    global _session_manager  # noqa: PLW0603
    if _session_manager is None:
        settings = get_settings()
        _session_manager = MCPSessionManager(
            max_sessions_per_server=settings.max_sessions_per_server,
            session_idle_timeout=settings.session_idle_timeout,
            session_cleanup_interval=settings.session_cleanup_interval,
            server_timeout=settings.server_timeout,
        )
    return _session_manager


def get_stdio_client() -> MCPStdioClient:
    """Return a new MCPStdioClient using the shared session manager."""
    return MCPStdioClient(session_manager=get_session_manager())


def get_sse_client() -> MCPSseClient:
    """Return a new MCPSseClient using the shared session manager."""
    return MCPSseClient(session_manager=get_session_manager())


async def cleanup_all() -> None:
    """Shut down all session managers. Called on microservice shutdown."""
    await cleanup_all_mcp_sessions()
    global _session_manager  # noqa: PLW0603
    _session_manager = None
    logger.info("All MCP sessions cleaned up")
