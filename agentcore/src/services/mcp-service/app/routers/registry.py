"""MCP Server Registry CRUD, test-connection, and probe endpoints."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.database import get_session
from app.models.registry import (
    McpProbeResponse,
    McpRegistryCreate,
    McpRegistryRead,
    McpRegistryUpdate,
    McpTestConnectionRequest,
    McpTestConnectionResponse,
    McpToolInfo,
)
from app.services import registry_service
from app.services.tool_service import list_tools, test_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/mcp", tags=["MCP Registry"])


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/servers", response_model=list[McpRegistryRead])
async def list_servers(
    active_only: bool = True,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """List all registered MCP servers."""
    return await registry_service.get_servers(session, active_only=active_only)


@router.post("/servers", response_model=McpRegistryRead, status_code=201)
async def create_server(
    body: McpRegistryCreate,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Register a new MCP server."""
    return await registry_service.create_server(session, body)


@router.get("/servers/{server_id}", response_model=McpRegistryRead)
async def get_server(
    server_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Get a single MCP server by ID."""
    result = await registry_service.get_server(session, server_id)
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return result


@router.put("/servers/{server_id}", response_model=McpRegistryRead)
async def update_server(
    server_id: UUID,
    body: McpRegistryUpdate,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Update an existing MCP server."""
    result = await registry_service.update_server(session, server_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return result


@router.delete("/servers/{server_id}", status_code=204)
async def delete_server(
    server_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Delete a registered MCP server."""
    deleted = await registry_service.delete_server(session, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP server not found")


# ---------------------------------------------------------------------------
# Test connection (ad-hoc)
# ---------------------------------------------------------------------------


@router.post("/test-connection", response_model=McpTestConnectionResponse)
async def test_mcp_connection(
    body: McpTestConnectionRequest,
    _api_key: str = Depends(verify_api_key),
):
    """Test connectivity to an MCP server (ad-hoc, not from registry)."""
    try:
        result = await test_connection(body.model_dump(), body.mode)
        return McpTestConnectionResponse(**result)
    except Exception as e:
        logger.warning("MCP test connection failed: %s", e)
        return McpTestConnectionResponse(success=False, message=str(e))


# ---------------------------------------------------------------------------
# Probe registered server
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/probe", response_model=McpProbeResponse)
async def probe_server(
    server_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Probe a registered MCP server: test connectivity and discover tools."""
    try:
        tool_schemas = await list_tools(
            server_id=str(server_id),
            session=session,
        )

        tools_info = [
            McpToolInfo(name=t.name, description=t.description)
            for t in tool_schemas
        ]

        return McpProbeResponse(
            success=True,
            message=f"Connected successfully. Found {len(tool_schemas)} tool(s).",
            tools_count=len(tool_schemas),
            tools=tools_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("MCP probe failed for server %s: %s", server_id, e)
        return McpProbeResponse(success=False, message=str(e))
