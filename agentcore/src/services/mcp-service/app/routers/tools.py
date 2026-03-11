"""Tool discovery and invocation endpoints."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.database import get_session
from app.schemas import InvokeToolRequest, InvokeToolResponse, ListToolsRequest, ListToolsResponse
from app.services.tool_service import invoke_tool, list_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/mcp", tags=["MCP Tools"])


@router.post("/servers/{server_id}/tools", response_model=ListToolsResponse)
async def discover_tools(
    server_id: UUID,
    body: ListToolsRequest | None = None,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Discover tools on a registered MCP server. Returns tool names and JSON Schemas."""
    try:
        session_context = body.session_context if body else None

        tool_schemas = await list_tools(
            server_id=str(server_id),
            session=session,
            session_context=session_context,
        )

        # Get server name for the response
        from app.services.registry_service import get_server

        server = await get_server(session, server_id)
        server_name = server.server_name if server else str(server_id)

        return ListToolsResponse(
            server_id=str(server_id),
            server_name=server_name,
            tools=tool_schemas,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Error discovering tools for server %s", server_id)
        raise HTTPException(status_code=500, detail=f"Tool discovery failed: {e!s}") from e


@router.post("/tools/invoke", response_model=InvokeToolResponse)
async def invoke_mcp_tool(
    body: InvokeToolRequest,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Invoke a specific tool on an MCP server."""
    try:
        result = await invoke_tool(
            server_id=body.server_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
            session=session,
            session_context=body.session_context,
        )
        return result
    except Exception as e:
        logger.exception("Error invoking tool '%s' on server '%s'", body.tool_name, body.server_id)
        return InvokeToolResponse(success=False, error=f"Tool invocation failed: {e!s}")
