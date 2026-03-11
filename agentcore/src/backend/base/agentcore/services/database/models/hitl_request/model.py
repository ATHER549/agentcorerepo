"""HITLRequest — tracks paused (interrupted) graph runs awaiting human input.

Each row corresponds to one LangGraph interrupt() call.  The thread_id links
back to LangGraph's checkpoints table so the run can be resumed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Boolean, Column, DateTime, Enum as SQLEnum, Index, Text
from sqlmodel import Field, SQLModel


class HITLStatus(str, Enum):
    """Lifecycle status of a human-in-the-loop request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class HITLRequest(SQLModel, table=True):  # type: ignore[call-arg]
    """Tracks a paused LangGraph run that is waiting for human input."""

    __tablename__ = "hitl_request"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # LangGraph thread that holds the frozen graph state in the checkpoints table.
    # index=True omitted here — the index is declared explicitly in __table_args__.
    thread_id: str = Field(sa_column=Column(Text, nullable=False))

    agent_id: UUID = Field(nullable=False)
    session_id: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    user_id: UUID | None = Field(default=None, nullable=True)

    # ── Routing fields (added for department-admin-based HIL approval) ───
    # For published/deployed runs, assigned_to points to the department admin
    # (or a delegatee).  For playground runs this stays None.
    assigned_to: UUID | None = Field(default=None, nullable=True)
    dept_id: UUID | None = Field(default=None, nullable=True)
    org_id: UUID | None = Field(default=None, nullable=True)
    is_deployed_run: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Delegation tracking — set when the department admin delegates to another user.
    delegated_by: UUID | None = Field(default=None, nullable=True)
    delegated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Payload produced by interrupt() — includes question, context, and action list.
    interrupt_data: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Raw value passed to interrupt({...})",
    )

    status: HITLStatus = Field(
        default=HITLStatus.PENDING,
        sa_column=Column(
            SQLEnum(
                HITLStatus,
                name="hitl_status_enum",
                values_callable=lambda e: [m.value for m in e],
            ),
            nullable=False,
        ),
    )

    # Human's response — e.g. {"action": "Approve", "feedback": "Looks good"}
    decision: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    decided_by_user_id: UUID | None = Field(default=None, nullable=True)

    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="now()"),
    )
    decided_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Non-null only when timeout_seconds > 0 was set on the component.
    timeout_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Serialized LangGraph checkpoint (base64-encoded pickle of MemorySaver storage).
    # Stored here so the checkpoint survives server restarts.  Restored to the
    # in-process MemorySaver before ainvoke(Command(resume=...)) is called.
    checkpoint_data: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    __table_args__ = (
        Index("ix_hitl_thread_id", "thread_id"),
        Index("ix_hitl_agent_id", "agent_id"),
        Index("ix_hitl_status", "status"),
        Index("ix_hitl_user_id", "user_id"),
        Index("ix_hitl_requested_at", "requested_at"),
        Index("ix_hitl_assigned_to", "assigned_to"),
    )


# ── Pydantic request/response schemas ────────────────────────────────────────

class HITLRequestRead(BaseModel):
    """Schema returned by the HITL API."""

    id: UUID
    thread_id: str
    agent_id: UUID
    agent_name: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[UUID] = None
    interrupt_data: Optional[dict] = None
    status: HITLStatus
    decision: Optional[dict] = None
    decided_by_user_id: Optional[UUID] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None
    timeout_at: Optional[datetime] = None
    # Routing fields
    assigned_to: Optional[UUID] = None
    assigned_to_name: Optional[str] = None
    dept_id: Optional[UUID] = None
    org_id: Optional[UUID] = None
    is_deployed_run: bool = False
    delegated_by: Optional[UUID] = None
    delegated_at: Optional[datetime] = None


class HITLResumeRequest(BaseModel):
    """Body for POST /hitl/{thread_id}/resume."""

    action: str
    feedback: Optional[str] = None
    edited_value: Optional[str] = None


class HITLDelegateRequest(BaseModel):
    """Body for POST /hitl/{thread_id}/delegate."""

    delegate_to_user_id: UUID
