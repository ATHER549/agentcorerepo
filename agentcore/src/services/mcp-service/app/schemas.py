"""Tool-specific schemas for the MCP microservice API."""

from __future__ import annotations

from pydantic import BaseModel


class ToolSchema(BaseModel):
    """Schema describing a single MCP tool (name, description, JSON Schema input)."""
    name: str
    description: str
    input_schema: dict


class ListToolsRequest(BaseModel):
    """Optional request body for tool listing."""
    session_context: str | None = None


class ListToolsResponse(BaseModel):
    """Response listing tools discovered on an MCP server."""
    server_id: str
    server_name: str
    tools: list[ToolSchema]


class InvokeToolRequest(BaseModel):
    """Request to invoke a specific tool on an MCP server."""
    server_id: str
    tool_name: str
    arguments: dict = {}
    session_context: str | None = None


class ToolContentItem(BaseModel):
    """A single content block from a tool invocation result."""
    type: str = "text"
    text: str | None = None
    mime_type: str | None = None
    data: str | None = None


class InvokeToolResponse(BaseModel):
    """Response from invoking a tool."""
    success: bool
    content: list[ToolContentItem] = []
    error: str | None = None
