from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy import Boolean
from sqlmodel import Field, SQLModel


class GuardrailVersion(SQLModel, table=True):  # type: ignore[call-arg]
    """Immutable versioned snapshot of a guardrail configuration.

    A new row is created each time an agent using this guardrail is deployed
    to production. The ``guardrail_snapshot`` JSON is frozen at creation time
    and must never be mutated.
    """

    __tablename__ = "guardrail_version"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    guardrail_id: UUID = Field(foreign_key="guardrail_catalogue.id", nullable=False, index=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    version_number: int = Field(
        sa_column=Column(Integer, nullable=False),
        description="Auto-increment per guardrail (v1, v2, v3).",
    )
    guardrail_snapshot: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False),
        description="Frozen copy of the guardrail configuration at deploy time. Immutable.",
    )
    guardrail_name: str = Field(
        sa_column=Column(String(255), nullable=False),
        description="Name of the guardrail at snapshot time.",
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, default=True),
        description="Whether this version is the currently active production version.",
    )
    status: str = Field(
        default="PUBLISHED",
        sa_column=Column(String(50), nullable=False, default="PUBLISHED"),
    )
    created_by: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("guardrail_id", "version_number", name="uq_guardrail_version_guardrail_version"),
        Index("ix_guardrail_version_guardrail_active", "guardrail_id", "is_active"),
        Index("ix_guardrail_version_org_id", "org_id"),
        Index("ix_guardrail_version_dept_id", "dept_id"),
    )


class GuardrailVersionRead(BaseModel):
    """Response schema for guardrail version data."""

    id: UUID
    guardrail_id: UUID
    org_id: UUID | None
    dept_id: UUID | None
    version_number: int
    guardrail_snapshot: dict[str, Any]
    guardrail_name: str
    is_active: bool
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, row: GuardrailVersion) -> GuardrailVersionRead:
        return cls(
            id=row.id,
            guardrail_id=row.guardrail_id,
            org_id=row.org_id,
            dept_id=row.dept_id,
            version_number=row.version_number,
            guardrail_snapshot=row.guardrail_snapshot,
            guardrail_name=row.guardrail_name,
            is_active=row.is_active,
            status=row.status,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    model_config = {"from_attributes": True}
