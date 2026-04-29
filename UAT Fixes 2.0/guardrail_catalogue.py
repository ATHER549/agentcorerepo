"""GuardrailCatalogue SQLModel table and Pydantic request/response schemas.

This mirrors the main backend's guardrail_catalogue table definition without FK
constraints to other agentcore tables (user, organization, department). The
microservice reads/writes only the guardrail_catalogue and model_registry tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# SQLModel table (mirrors backend GuardrailCatalogue — no FK constraints here)
# ---------------------------------------------------------------------------


class GuardrailCatalogue(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "guardrail_catalogue"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    framework: str = Field(
        default="nemo",
        sa_column=Column(String(50), nullable=False, default="nemo", index=True),
    )
    provider: str = Field(sa_column=Column(String(100), nullable=False, index=True))
    model_registry_id: UUID | None = Field(default=None, nullable=True, index=True)
    category: str = Field(sa_column=Column(String(50), nullable=False, index=True))
    status: str = Field(default="active", sa_column=Column(String(50), nullable=False, index=True))
    rules_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    is_custom: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    runtime_config: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    visibility: str = Field(
        default="private",
        sa_column=Column(String(20), nullable=False, default="private"),
    )
    public_scope: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    shared_user_ids: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    public_dept_ids: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    org_id: UUID | None = Field(default=None, nullable=True)
    dept_id: UUID | None = Field(default=None, nullable=True)

    created_by: UUID | None = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_by: UUID | None = Field(default=None, nullable=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    published_by: UUID | None = Field(default=None, nullable=True)
    published_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # ── Environment separation (UAT / PROD) ──
    environment: str = Field(
        default="uat",
        sa_column=Column(String(10), nullable=False, default="uat", index=True),
    )
    source_guardrail_id: UUID | None = Field(
        default=None,
        sa_column=Column(PG_UUID(as_uuid=True), nullable=True, index=True),
    )
    promoted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    promoted_by: UUID | None = Field(default=None, nullable=True)
    latest_version: int = Field(
    default=1,
    sa_column=Column(Integer, nullable=False, default=1)
    )
    prod_ref_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))

    class Config:
        # Disable automatic table arg generation to avoid FK constraint conflicts
        arbitrary_types_allowed = True


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class GuardrailCatalogueCreate(BaseModel):
    name: str
    description: str | None = None
    framework: str = "nemo"
    provider: str
    model_registry_id: UUID | None = None
    category: str
    status: str = "active"
    rules_count: int = 0
    is_custom: bool = False
    runtime_config: dict[str, Any] | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str = "private"
    public_scope: str | None = None
    public_dept_ids: list[str] | None = None
    shared_user_ids: list[str] | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None
    published_by: UUID | None = None
    published_at: datetime | None = None


class GuardrailCatalogueUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    framework: str | None = None
    provider: str | None = None
    model_registry_id: UUID | None = None
    category: str | None = None
    status: str | None = None
    rules_count: int | None = None
    is_custom: bool | None = None
    runtime_config: dict[str, Any] | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str | None = None
    public_scope: str | None = None
    public_dept_ids: list[str] | None = None
    shared_user_ids: list[str] | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None
    published_by: UUID | None = None
    published_at: datetime | None = None


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class GuardrailCatalogueRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    framework: str
    provider: str
    model_registry_id: UUID | None
    category: str
    status: str
    rules_count: int
    is_custom: bool
    runtime_config: dict[str, Any] | None
    org_id: UUID | None
    dept_id: UUID | None
    visibility: str
    public_scope: str | None
    public_dept_ids: list[str] | None
    shared_user_ids: list[str] | None
    created_by: UUID | None
    created_at: datetime
    updated_by: UUID | None
    updated_at: datetime
    published_by: UUID | None
    published_at: datetime | None
    # Environment separation fields
    environment: str = "uat"
    source_guardrail_id: UUID | None = None
    promoted_at: datetime | None = None
    promoted_by: UUID | None = None
    prod_ref_count: int = 0

    @classmethod
    def from_orm_model(cls, row: GuardrailCatalogue) -> "GuardrailCatalogueRead":
        return cls(
            id=row.id,
            name=row.name,
            description=row.description,
            framework=row.framework,
            provider=row.provider,
            model_registry_id=row.model_registry_id,
            category=row.category,
            status=row.status,
            rules_count=row.rules_count,
            is_custom=row.is_custom,
            runtime_config=row.runtime_config,
            org_id=row.org_id,
            dept_id=row.dept_id,
            visibility=row.visibility,
            public_scope=row.public_scope,
            public_dept_ids=row.public_dept_ids,
            shared_user_ids=row.shared_user_ids,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_by=row.updated_by,
            updated_at=row.updated_at,
            published_by=row.published_by,
            published_at=row.published_at,
            environment=row.environment,
            source_guardrail_id=row.source_guardrail_id,
            promoted_at=row.promoted_at,
            promoted_by=row.promoted_by,
            prod_ref_count=row.prod_ref_count,
        )

    model_config = {"from_attributes": True}
