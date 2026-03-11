from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel


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
    model_registry_id: UUID | None = Field(default=None, foreign_key="model_registry.id", nullable=True, index=True)
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

    # NULL org_id + NULL dept_id => global scope
    # org_id + NULL dept_id => organization scope
    # org_id + dept_id => department scope
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)

    created_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    published_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    published_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    __table_args__ = (
        CheckConstraint("(dept_id IS NULL) OR (org_id IS NOT NULL)", name="ck_guardrail_scope_consistency"),
        ForeignKeyConstraint(
            ["org_id", "dept_id"],
            ["department.org_id", "department.id"],
            name="fk_guardrail_org_dept_department",
        ),
        UniqueConstraint("org_id", "dept_id", "name", name="uq_guardrail_scope_name"),
        Index("ix_guardrail_org_id", "org_id"),
        Index("ix_guardrail_dept_id", "dept_id"),
        Index("ix_guardrail_org_dept", "org_id", "dept_id"),
    )
