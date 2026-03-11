# TARGET PATH: src/backend/base/agentcore/schema/a2a.py
"""A2A (Agent-to-Agent) Protocol Schemas.

Pydantic models following the Google A2A protocol specification.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class A2AAgentConfigSchema(BaseModel):
    """Schema for A2A agent configuration."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    prompt: str
    llm_override: str | None = None


class A2AAgentCardSchema(BaseModel):
    """Schema for A2A Agent Card (Google A2A spec).

    An Agent Card describes an agent's capabilities, identity,
    and how to communicate with it.
    """

    name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    supported_content_types: list[str] = Field(
        default=["text/plain", "application/json"]
    )
    version: str = "1.0"
    endpoint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2ATaskSchema(BaseModel):
    """Schema for A2A Task."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = ""
    input_data: str
    expected_output: str | None = None
    status: Literal["pending", "running", "completed", "failed", "cancelled"] = (
        "pending"
    )
    result: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2AMessageSchema(BaseModel):
    """Schema for A2A Message."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    sender_id: str
    receiver_id: str
    content: str
    message_type: Literal[
        "task_request",
        "task_response",
        "task_update",
        "error",
        "acknowledgment",
        "child_agent_invoke",
        "child_agent_result",
    ] = "task_request"
    timestamp: datetime = Field(default_factory=datetime.now)
    parent_message_id: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)


class A2AGroupConfigSchema(BaseModel):
    """Schema for A2A group configuration."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    agents: list[A2AAgentConfigSchema] = Field(min_length=2)
    communication_mode: Literal["sequential"] = "sequential"
    default_llm: str | None = None


class A2AConversationLogSchema(BaseModel):
    """Schema for A2A conversation log."""

    group_id: str
    messages: list[A2AMessageSchema]
    start_time: datetime
    end_time: datetime | None = None
    status: Literal["running", "completed", "error"] = "running"
