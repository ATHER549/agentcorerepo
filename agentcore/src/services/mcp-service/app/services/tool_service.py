"""Core business logic for tool discovery and invocation."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp_clients.helpers import extract_tool_result, process_headers, validate_connection_params
from app.schemas import InvokeToolResponse, ToolContentItem, ToolSchema
from app.services.registry_service import get_decrypted_config_by_id
from app.services.session_service import get_sse_client, get_stdio_client

logger = logging.getLogger(__name__)


async def list_tools(
    server_id: str,
    session: AsyncSession,
    session_context: str | None = None,
) -> list[ToolSchema]:
    """Discover tools on a registered MCP server.

    1. Fetch decrypted config from registry
    2. Determine mode (stdio/sse)
    3. Connect via appropriate client
    4. Call session.list_tools()
    5. Return tool schemas with raw inputSchema dicts
    """
    result = await get_decrypted_config_by_id(session, UUID(server_id))
    if result is None:
        msg = f"MCP server {server_id} not found"
        raise ValueError(msg)

    server_name, server_config = result
    return await _discover_tools(server_name, server_config, session_context)


async def list_tools_from_config(
    server_config: dict,
    server_name: str = "ad-hoc",
    session_context: str | None = None,
) -> list[ToolSchema]:
    """Discover tools using an ad-hoc config (for test-connection)."""
    return await _discover_tools(server_name, server_config, session_context)


async def _discover_tools(
    server_name: str,
    server_config: dict,
    session_context: str | None = None,
) -> list[ToolSchema]:
    """Internal: connect and discover tools."""
    mode = "Stdio" if "command" in server_config else "SSE" if "url" in server_config else ""
    command = server_config.get("command", "")
    url = server_config.get("url", "")

    await validate_connection_params(mode, command, url)

    tools = []

    if mode == "Stdio":
        client = get_stdio_client()
        if session_context:
            client.set_session_context(session_context)
        args = server_config.get("args", [])
        env = server_config.get("env", {})
        full_command = " ".join([command, *args])
        mcp_tools = await client.connect_to_server(full_command, env)
        tools = mcp_tools
    elif mode == "SSE":
        client = get_sse_client()
        if session_context:
            client.set_session_context(session_context)
        headers = process_headers(server_config.get("headers", {}))
        mcp_tools = await client.connect_to_server(url, headers=headers)
        tools = mcp_tools
    else:
        logger.error(f"Invalid MCP server mode for '{server_name}': {mode}")
        return []

    tool_schemas = []
    for tool in tools:
        if not tool or not hasattr(tool, "name"):
            continue
        tool_schemas.append(
            ToolSchema(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
            )
        )

    logger.info(f"Discovered {len(tool_schemas)} tools from MCP server '{server_name}'")
    return tool_schemas


async def invoke_tool(
    server_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    session: AsyncSession,
    session_context: str | None = None,
) -> InvokeToolResponse:
    """Invoke a specific tool on a registered MCP server.

    1. Fetch decrypted config
    2. Connect/reuse session (session_context for affinity)
    3. Call client.run_tool(tool_name, arguments)
    4. Extract content items and return
    """
    result = await get_decrypted_config_by_id(session, UUID(server_id))
    if result is None:
        return InvokeToolResponse(success=False, error=f"MCP server {server_id} not found")

    server_name, server_config = result

    try:
        mode = "Stdio" if "command" in server_config else "SSE" if "url" in server_config else ""
        command = server_config.get("command", "")
        url = server_config.get("url", "")

        await validate_connection_params(mode, command, url)

        if mode == "Stdio":
            client = get_stdio_client()
            if session_context:
                client.set_session_context(session_context)
            args = server_config.get("args", [])
            env = server_config.get("env", {})
            full_command = " ".join([command, *args])
            await client.connect_to_server(full_command, env)
            raw_result = await client.run_tool(tool_name, arguments)
        elif mode == "SSE":
            client = get_sse_client()
            if session_context:
                client.set_session_context(session_context)
            headers = process_headers(server_config.get("headers", {}))
            await client.connect_to_server(url, headers=headers)
            raw_result = await client.run_tool(tool_name, arguments)
        else:
            return InvokeToolResponse(success=False, error=f"Invalid mode for server '{server_name}'")

        # Extract content items from the raw MCP result
        content_items = _extract_content_items(raw_result)
        return InvokeToolResponse(success=True, content=content_items)

    except Exception as e:
        logger.error(f"Tool '{tool_name}' invocation failed on server '{server_name}': {e}")
        return InvokeToolResponse(success=False, error=str(e))


def _extract_content_items(result: Any) -> list[ToolContentItem]:
    """Convert an MCP CallToolResult into a list of ToolContentItem."""
    if result is None:
        return [ToolContentItem(type="text", text="")]

    if isinstance(result, str):
        return [ToolContentItem(type="text", text=result)]

    items: list[ToolContentItem] = []
    content_list = getattr(result, "content", None)
    if content_list:
        for block in content_list:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                items.append(ToolContentItem(type="text", text=getattr(block, "text", "")))
            elif block_type == "image":
                mime = getattr(block, "mimeType", "image/png")
                data = getattr(block, "data", "")
                items.append(ToolContentItem(type="image", mime_type=mime, data=data))
            else:
                text = getattr(block, "text", None) or str(block)
                items.append(ToolContentItem(type="text", text=text))

    # Also include structuredContent if present
    structured = getattr(result, "structuredContent", None)
    if structured:
        import json
        items.append(ToolContentItem(type="text", text=json.dumps(structured, ensure_ascii=False)))

    if not items:
        items.append(ToolContentItem(type="text", text=str(result)))

    return items


async def test_connection(config: dict, mode: str) -> dict:
    """Test an ad-hoc MCP connection.

    Returns a dict with success, message, tools_count.
    """
    server_config: dict = {}
    if mode == "sse":
        if config.get("url"):
            server_config["url"] = config["url"]
        if config.get("headers"):
            server_config["headers"] = config["headers"]
    elif mode == "stdio":
        if config.get("command"):
            server_config["command"] = config["command"]
        if config.get("args"):
            server_config["args"] = config["args"]

    if config.get("env_vars"):
        server_config["env"] = config["env_vars"]

    try:
        tool_schemas = await list_tools_from_config(server_config, server_name="test-connection")
        return {
            "success": True,
            "message": f"Connected successfully. Found {len(tool_schemas)} tool(s).",
            "tools_count": len(tool_schemas),
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "tools_count": None,
        }
