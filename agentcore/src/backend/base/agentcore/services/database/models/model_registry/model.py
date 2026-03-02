"""ModelRegistry SQLModel table and Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, computed_field
from sqlalchemy import JSON, Column, DateTime, String, Text, text
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ModelEnvironment(str, Enum):
    """Environment where the model is deployed / available."""

    TEST = "test"
    UAT = "uat"
    PROD = "prod"


class ModelVisibilityScope(str, Enum):
    """Visibility scope for model consumption."""

    PRIVATE = "private"
    DEPARTMENT = "department"
    ORGANIZATION = "organization"


class ModelApprovalStatus(str, Enum):
    """Approval lifecycle for model records."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# SQLModel table
# ---------------------------------------------------------------------------

class ModelRegistry(SQLModel, table=True):
    """Persisted model configuration in the registry."""

    __tablename__ = "model_registry"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    display_name: str = Field(nullable=False)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    provider: str = Field(nullable=False, index=True)
    model_name: str = Field(nullable=False)
    model_type: str = Field(default="llm", index=True)  # "llm" or "embedding"
    base_url: str | None = Field(default=None)
    api_key_encrypted: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    # Environment tag: test (default), uat, prod
    environment: str = Field(default=ModelEnvironment.TEST.value, index=True)
    source_model_id: UUID | None = Field(default=None, foreign_key="model_registry.id", nullable=True, index=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    public_dept_ids: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_by_id: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    visibility_scope: str = Field(
        default=ModelVisibilityScope.PRIVATE.value,
        sa_column=Column(String(20), nullable=False, server_default=text("'private'")),
    )
    approval_status: str = Field(
        default=ModelApprovalStatus.APPROVED.value,
        sa_column=Column(String(20), nullable=False, server_default=text("'approved'")),
    )
    requested_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    request_to: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    requested_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    reviewed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    reviewed_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    review_comments: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    review_attachments: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Provider-specific connection fields (azure_deployment, api_version, organization, custom_headers, etc.)
    provider_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Model capabilities flags
    capabilities: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Default inference parameters (temperature, max_tokens, top_p, top_k, thinking_budget, model_kwargs, etc.)
    default_params: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    is_active: bool = Field(default=True)
    created_by: str | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ModelRegistryCreate(BaseModel):
    """Payload for creating a new registry entry."""

    display_name: str
    description: str | None = None
    provider: str
    model_name: str
    model_type: str = "llm"  # "llm" or "embedding"
    base_url: str | None = None
    api_key: str | None = None  # plain-text; encrypted before storage
    environment: str = ModelEnvironment.TEST.value  # defaults to test
    visibility_scope: str = ModelVisibilityScope.PRIVATE.value
    org_id: UUID | None = None
    dept_id: UUID | None = None
    public_dept_ids: list[UUID] | None = None
    provider_config: dict | None = None
    capabilities: dict | None = None
    default_params: dict | None = None
    is_active: bool = True
    created_by: str | None = None
    created_by_id: UUID | None = None
    approval_status: str = ModelApprovalStatus.APPROVED.value
    requested_by: UUID | None = None
    request_to: UUID | None = None
    requested_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    review_comments: str | None = None
    review_attachments: dict | None = None


class ModelRegistryUpdate(BaseModel):
    """Payload for updating an existing registry entry.  All fields optional."""

    display_name: str | None = None
    description: str | None = None
    provider: str | None = None
    model_name: str | None = None
    model_type: str | None = None  # "llm" or "embedding"
    base_url: str | None = None
    api_key: str | None = None  # plain-text; re-encrypted if provided
    environment: str | None = None
    visibility_scope: str | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    public_dept_ids: list[UUID] | None = None
    provider_config: dict | None = None
    capabilities: dict | None = None
    default_params: dict | None = None
    is_active: bool | None = None
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

class ModelRegistryRead(BaseModel):
    """Safe representation returned to callers - never includes the encrypted key."""

    id: UUID
    display_name: str
    description: str | None = None
    provider: str
    model_name: str
    model_type: str = "llm"
    base_url: str | None = None
    environment: str = ModelEnvironment.TEST.value
    source_model_id: UUID | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    public_dept_ids: list[str] | None = None
    visibility_scope: str = ModelVisibilityScope.PRIVATE.value
    approval_status: str = ModelApprovalStatus.APPROVED.value
    requested_by: UUID | None = None
    request_to: UUID | None = None
    requested_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    review_comments: str | None = None
    review_attachments: dict | None = None
    provider_config: dict | None = None
    capabilities: dict | None = None
    default_params: dict | None = None
    is_active: bool
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # Computed from the DB row - tells the frontend whether an API key is stored.
    _has_api_key: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_api_key(self) -> bool:
        return self._has_api_key

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, row: ModelRegistry) -> "ModelRegistryRead":
        obj = cls.model_validate(row)
        object.__setattr__(obj, "_has_api_key", bool(row.api_key_encrypted))
        return obj


# ---------------------------------------------------------------------------
# Test-connection request
# ---------------------------------------------------------------------------

class TestConnectionRequest(BaseModel):
    provider: str
    model_name: str
    base_url: str | None = None
    api_key: str | None = None
    provider_config: dict | None = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    latency_ms: float | None = None
