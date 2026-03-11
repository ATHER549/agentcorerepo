from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, Index, String, Text, text
from sqlmodel import Field, SQLModel

from agentcore.services.database.models.approval_request.model import ApprovalDecisionEnum


class McpApprovalRequestBase(SQLModel):
    mcp_id: UUID = Field(foreign_key="mcp_registry.id", nullable=False, description="MCP server under review")
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    requested_by: UUID = Field(foreign_key="user.id", nullable=False)
    request_to: UUID = Field(foreign_key="user.id", nullable=False)
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    reviewed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    decision: ApprovalDecisionEnum | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    justification: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    file_path: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    deployment_env: str = Field(
        default="DEV",
        sa_column=Column(String(10), nullable=False, server_default=text("'DEV'")),
        description="Environment discriminator: DEV, UAT, or PROD",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )


class McpApprovalRequest(McpApprovalRequestBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "mcp_approval_request"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    __table_args__ = (
        Index("ix_mcp_approval_mcp_id", "mcp_id"),
        Index("ix_mcp_approval_org", "org_id"),
        Index("ix_mcp_approval_dept", "dept_id"),
        Index("ix_mcp_approval_request_to_decision", "request_to", "decision"),
        Index("ix_mcp_approval_requested_by_decision", "requested_by", "decision"),
    )


class McpApprovalRequestCreate(SQLModel):
    mcp_id: UUID
    requested_by: UUID
    request_to: UUID
    org_id: UUID | None = None
    dept_id: UUID | None = None
    deployment_env: str = "DEV"


class McpApprovalRequestRead(BaseModel):
    id: UUID
    mcp_id: UUID
    org_id: UUID | None = None
    dept_id: UUID | None = None
    requested_by: UUID
    request_to: UUID
    requested_at: datetime
    reviewed_at: datetime | None = None
    decision: ApprovalDecisionEnum | None = None
    justification: str | None = None
    file_path: dict | None = None
    deployment_env: str
    created_at: datetime
    updated_at: datetime


class McpApprovalRequestUpdate(BaseModel):
    reviewed_at: datetime | None = None
    decision: ApprovalDecisionEnum | None = None
    justification: str | None = None
    file_path: dict | None = None
