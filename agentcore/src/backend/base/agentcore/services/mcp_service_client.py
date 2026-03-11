"""HTTP client for the MCP microservice.

Bridges agentcore backend to the standalone MCP microservice by
proxying registry CRUD, tool discovery, and tool invocation requests.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _get_mcp_service_settings() -> tuple[str, str]:
    """Get MCP service URL and API key from agentcore settings."""
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    url = getattr(settings, "mcp_service_url", "")
    api_key = getattr(settings, "mcp_service_api_key", "")

    if not url:
        msg = "MCP_SERVICE_URL is not configured. Set it in your environment or .env file."
        raise ValueError(msg)

    return url.rstrip("/"), api_key or ""


def _headers(api_key: str) -> dict[str, str]:
    """Build standard headers for MCP service requests."""
    h = {"Content-Type": "application/json"}
    if api_key:
        h["x-api-key"] = api_key
    return h


def is_service_configured() -> bool:
    """Check whether the MCP service URL is configured (non-empty)."""
    try:
        _get_mcp_service_settings()
        return True
    except (ValueError, Exception):
        return False


# ---------------------------------------------------------------------------
# Registry proxy functions
# ---------------------------------------------------------------------------


async def fetch_mcp_servers_async(
    active_only: bool = True,
) -> list[dict]:
    """Fetch MCP servers from the microservice (async)."""
    try:
        url, api_key = _get_mcp_service_settings()
    except ValueError:
        return []

    params: dict = {}
    if not active_only:
        params["active_only"] = "false"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{url}/v1/mcp/servers",
                headers=_headers(api_key),
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning("Failed to fetch MCP servers from MCP service: %s", e)
        return []


async def create_mcp_server_via_service(body: dict) -> dict:
    """Create a MCP server via the microservice."""
    url, api_key = _get_mcp_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{url}/v1/mcp/servers",
            headers=_headers(api_key),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def get_mcp_server_via_service(server_id: str) -> dict | None:
    """Get an MCP server by ID via the microservice."""
    url, api_key = _get_mcp_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{url}/v1/mcp/servers/{server_id}",
            headers=_headers(api_key),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


async def update_mcp_server_via_service(server_id: str, body: dict) -> dict | None:
    """Update an MCP server via the microservice."""
    url, api_key = _get_mcp_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(
            f"{url}/v1/mcp/servers/{server_id}",
            headers=_headers(api_key),
            json=body,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


async def delete_mcp_server_via_service(server_id: str) -> bool:
    """Delete an MCP server via the microservice."""
    url, api_key = _get_mcp_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(
            f"{url}/v1/mcp/servers/{server_id}",
            headers=_headers(api_key),
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True


# ---------------------------------------------------------------------------
# Test connection / Probe
# ---------------------------------------------------------------------------


async def test_mcp_connection_via_service(body: dict) -> dict:
    """Test an MCP connection via the microservice."""
    url, api_key = _get_mcp_service_settings()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{url}/v1/mcp/test-connection",
            headers=_headers(api_key),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def probe_mcp_server_via_service(server_id: str) -> dict:
    """Probe a registered MCP server via the microservice."""
    url, api_key = _get_mcp_service_settings()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{url}/v1/mcp/servers/{server_id}/probe",
            headers=_headers(api_key),
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Tool discovery and invocation
# ---------------------------------------------------------------------------


async def list_tools_via_service(
    server_id: str,
    session_context: str | None = None,
) -> list[dict]:
    """Discover tools on an MCP server via the microservice.

    Returns a list of dicts with keys: name, description, input_schema.
    """
    url, api_key = _get_mcp_service_settings()
    body: dict = {}
    if session_context:
        body["session_context"] = session_context

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{url}/v1/mcp/servers/{server_id}/tools",
            headers=_headers(api_key),
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("tools", [])


async def invoke_tool_via_service(
    server_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    session_context: str | None = None,
) -> dict:
    """Invoke a tool on an MCP server via the microservice.

    Returns a dict with keys: success, content (list of items), error.
    """
    url, api_key = _get_mcp_service_settings()
    body = {
        "server_id": server_id,
        "tool_name": tool_name,
        "arguments": arguments or {},
    }
    if session_context:
        body["session_context"] = session_context

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{url}/v1/mcp/tools/invoke",
            headers=_headers(api_key),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()
