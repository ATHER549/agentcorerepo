"""GuardrailVersion SQLModel table and Pydantic response schema.

This mirrors the main backend's guardrail_version table definition without FK
constraints to other agentcore tables. The microservice reads/writes only the
guardrail_version and guardrail_catalogue tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


class GuardrailVersion(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "guardrail_version"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    guardrail_id: UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), nullable=False, index=True),
    )
    org_id: UUID | None = Field(default=None, nullable=True)
    dept_id: UUID | None = Field(default=None, nullable=True)
    version_number: int = Field(sa_column=Column(Integer, nullable=False))
    guardrail_snapshot: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False),
    )
    guardrail_name: str = Field(sa_column=Column(String(255), nullable=False))
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, default=True),
    )
    status: str = Field(
        default="PUBLISHED",
        sa_column=Column(String(50), nullable=False, default="PUBLISHED"),
    )
    created_by: UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), nullable=False, index=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    class Config:
        arbitrary_types_allowed = True


class GuardrailVersionRead(BaseModel):
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
    def from_orm_model(cls, row: GuardrailVersion) -> "GuardrailVersionRead":
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
