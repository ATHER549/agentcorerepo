"""McpRegistry SQLModel table and Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, computed_field
from sqlalchemy import JSON, Column, DateTime, ForeignKeyConstraint, Index, String, Text
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# SQLModel table
# ---------------------------------------------------------------------------

class McpRegistry(SQLModel, table=True):
    """Global MCP server configuration stored in the registry."""

    __tablename__ = "mcp_registry"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    server_name: str = Field(nullable=False, index=True, unique=True)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    mode: str = Field(nullable=False)  # "sse" or "stdio"
    deployment_env: str = Field(
        default="DEV",
        sa_column=Column(String(10), nullable=False, default="DEV", index=True),
    )  # DEV | UAT | PROD

    # SSE-specific
    url: str | None = Field(default=None)

    # STDIO-specific
    command: str | None = Field(default=None)
    args: list | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Secrets (encrypted JSON)
    env_vars_encrypted: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    headers_encrypted: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    is_active: bool = Field(default=True)  # Runtime enabled flag after approval
    status: str = Field(default="disconnected", sa_column=Column(String(50), nullable=False, default="disconnected"))

    visibility: str = Field(
        default="private",
        sa_column=Column(String(20), nullable=False, default="private"),
    )
    public_scope: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    public_dept_ids: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    shared_user_ids: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)

    approval_status: str = Field(
        default="approved",
        sa_column=Column(String(20), nullable=False, default="approved", index=True),
    )  # pending | approved | rejected
    requested_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    request_to: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    requested_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    reviewed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    reviewed_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    review_comments: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    review_attachments: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    created_by: str | None = Field(default=None, nullable=True)
    created_by_id: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "dept_id"],
            ["department.org_id", "department.id"],
            name="fk_mcp_registry_org_dept_department",
        ),
        Index("ix_mcp_registry_org_dept", "org_id", "dept_id"),
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class McpRegistryCreate(BaseModel):
    """Payload for registering a new MCP server."""

    server_name: str
    description: str | None = None
    mode: str  # "sse" or "stdio"
    deployment_env: str = "DEV"
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env_vars: dict[str, str] | None = None  # plain-text; encrypted before storage
    headers: dict[str, str] | None = None  # plain-text; encrypted before storage
    is_active: bool = True
    status: str = "disconnected"
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str = "private"
    public_scope: str | None = None
    public_dept_ids: list[UUID] | None = None
    shared_user_emails: list[str] | None = None
    shared_user_ids: list[str] | None = None
    approval_status: str = "approved"
    requested_by: UUID | None = None
    request_to: UUID | None = None
    requested_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    review_comments: str | None = None
    review_attachments: dict | None = None
    created_by: str | None = None
    created_by_id: UUID | None = None


class McpRegistryUpdate(BaseModel):
    """Payload for updating an existing MCP server. All fields optional."""

    server_name: str | None = None
    description: str | None = None
    mode: str | None = None
    deployment_env: str | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env_vars: dict[str, str] | None = None  # plain-text; re-encrypted if provided
    headers: dict[str, str] | None = None  # plain-text; re-encrypted if provided
    is_active: bool | None = None
    status: str | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str | None = None
    public_scope: str | None = None
    public_dept_ids: list[UUID] | None = None
    shared_user_ids: list[str] | None = None
    approval_status: str | None = None
    requested_by: UUID | None = None
    request_to: UUID | None = None
    requested_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    review_comments: str | None = None
    review_attachments: dict | None = None


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

class McpRegistryRead(BaseModel):
    """Safe representation returned to callers - never includes encrypted secrets."""

    id: UUID
    server_name: str
    description: str | None = None
    mode: str
    deployment_env: str = "DEV"
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    is_active: bool
    status: str = "disconnected"
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str = "private"
    public_scope: str | None = None
    public_dept_ids: list[str] | None = None
    shared_user_ids: list[str] | None = None
    approval_status: str = "approved"
    requested_by: UUID | None = None
    request_to: UUID | None = None
    requested_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    review_comments: str | None = None
    review_attachments: dict | None = None
    created_by: str | None = None
    created_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    _has_env_vars: bool = False
    _has_headers: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_env_vars(self) -> bool:
        return self._has_env_vars

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_headers(self) -> bool:
        return self._has_headers

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, row: McpRegistry) -> "McpRegistryRead":
        obj = cls.model_validate(row)
        object.__setattr__(obj, "_has_env_vars", bool(row.env_vars_encrypted))
        object.__setattr__(obj, "_has_headers", bool(row.headers_encrypted))
        return obj


# ---------------------------------------------------------------------------
# Test-connection request
# ---------------------------------------------------------------------------

class McpTestConnectionRequest(BaseModel):
    mode: str  # "sse" or "stdio"
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env_vars: dict[str, str] | None = None
    headers: dict[str, str] | None = None


class McpTestConnectionResponse(BaseModel):
    success: bool
    message: str
    tools_count: int | None = None


# ---------------------------------------------------------------------------
# Probe response (registered server)
# ---------------------------------------------------------------------------

class McpToolInfo(BaseModel):
    """Information about a single tool discovered on an MCP server."""
    name: str
    description: str


class McpProbeResponse(BaseModel):
    """Response from probing a registered MCP server for connectivity and tools."""
    success: bool
    message: str
    tools_count: int | None = None
    tools: list[McpToolInfo] | None = None
