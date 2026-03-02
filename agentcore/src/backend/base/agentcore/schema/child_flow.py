# TARGET PATH: src/backend/base/agentcore/schema/child_flow.py
"""Child Flow Schemas.

Pydantic models for child flow communication and configuration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from agentcore.schema.a2a import A2AMessageSchema


class ParentFlowContextSchema(BaseModel):
    """Context passed from parent to child flow."""

    parent_flow_id: str
    parent_flow_name: str
    session_id: str | None = None
    call_depth: int = 0
    a2a_task_id: str = Field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChildFlowResultSchema(BaseModel):
    """Result returned from child flow to parent."""

    output: str
    status: Literal["success", "error"]
    a2a_messages: list[A2AMessageSchema] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    error: str | None = None


class ChildFlowConfigSchema(BaseModel):
    """Configuration for a child flow call."""

    child_flow_name: str
    input_value: str
    session_id: str | None = None
    enable_a2a_logging: bool = True
    tweaks: dict[str, Any] = Field(default_factory=dict)


class ChildFlowConversationLogSchema(BaseModel):
    """Complete conversation log for a child flow execution."""

    parent_flow_id: str
    parent_flow_name: str
    child_flow_id: str
    child_flow_name: str
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: datetime | None = None
    status: Literal["pending", "running", "completed", "error"] = "pending"
    messages: list[A2AMessageSchema] = Field(default_factory=list)
    result: ChildFlowResultSchema | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "parent_flow_id": self.parent_flow_id,
            "parent_flow_name": self.parent_flow_name,
            "child_flow_id": self.child_flow_id,
            "child_flow_name": self.child_flow_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "messages": [msg.model_dump() for msg in self.messages],
            "result": self.result.model_dump() if self.result else None,
        }
