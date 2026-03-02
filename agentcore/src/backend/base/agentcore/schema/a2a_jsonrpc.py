# TARGET PATH: src/backend/base/agentcore/schema/a2a_jsonrpc.py
"""JSON-RPC 2.0 Schemas for A2A Protocol.

This module provides Pydantic models for the Google A2A protocol
using JSON-RPC 2.0 over HTTP.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class JsonRpcErrorCode(IntEnum):
    """JSON-RPC 2.0 Standard Error Codes and A2A Custom Codes."""

    # Standard JSON-RPC 2.0 error codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Custom A2A error codes (-32000 to -32099 reserved for implementation)
    TASK_NOT_FOUND = -32000
    FLOW_NOT_FOUND = -32001
    EXECUTION_ERROR = -32002
    UNAUTHORIZED = -32003
    TASK_CANCELLED = -32004


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 Request."""

    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: dict[str, Any] | None = None
    id: str | int | None = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 Error object."""

    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 Response."""

    jsonrpc: Literal["2.0"] = "2.0"
    result: Any | None = None
    error: JsonRpcError | None = None
    id: str | int | None = None


# A2A Message Content schemas


class A2AMessageContent(BaseModel):
    """Content for A2A messages."""

    type: Literal["text", "json"] = "text"
    text: str | None = None
    data: dict[str, Any] | None = None


class A2ASendParams(BaseModel):
    """Parameters for message/send method."""

    message: A2AMessageContent
    session_id: str | None = None
    metadata: dict[str, Any] | None = None


class A2ATasksGetParams(BaseModel):
    """Parameters for tasks/get method."""

    task_id: str


class A2ATasksCancelParams(BaseModel):
    """Parameters for tasks/cancel method."""

    task_id: str


class A2ATaskInfo(BaseModel):
    """Task information in responses."""

    id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    created_at: datetime
    completed_at: datetime | None = None


class A2ASendResult(BaseModel):
    """Result for message/send method."""

    task: A2ATaskInfo
    content: A2AMessageContent | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class A2ATasksGetResult(BaseModel):
    """Result for tasks/get method."""

    task: A2ATaskInfo
    result: str | None = None
    error: str | None = None


class A2ATasksCancelResult(BaseModel):
    """Result for tasks/cancel method."""

    success: bool
    task_id: str
    message: str


# Agent Card schema (Google A2A spec compliant)


class A2AAgentCardResponse(BaseModel):
    """Agent Card for flow discovery following Google A2A specification."""

    name: str
    description: str
    url: str  # The RPC endpoint URL
    version: str = "1.0"
    capabilities: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] | None = None  # JSON Schema for flow inputs
    supported_methods: list[str] = Field(
        default=["message/send", "tasks/get", "tasks/cancel"]
    )
    authentication: dict[str, Any] = Field(
        default_factory=lambda: {"type": "api_key", "header": "x-api-key"}
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
