from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, Index, String, Text, text
from sqlmodel import Field, SQLModel


class ModelAuditLog(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "model_audit_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    model_id: UUID | None = Field(default=None, foreign_key="model_registry.id", nullable=True, index=True)
    action: str = Field(
        default="unknown",
        sa_column=Column(String(80), nullable=False, server_default=text("'unknown'")),
    )
    actor_id: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    from_environment: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    to_environment: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    from_visibility: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    to_visibility: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    details: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )

    __table_args__ = (
        Index("ix_model_audit_action_created", "action", "created_at"),
        Index("ix_model_audit_actor_created", "actor_id", "created_at"),
    )


class ModelAuditLogRead(BaseModel):
    id: UUID
    model_id: UUID | None = None
    action: str
    actor_id: UUID | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    from_environment: str | None = None
    to_environment: str | None = None
    from_visibility: str | None = None
    to_visibility: str | None = None
    details: dict | None = None
    message: str | None = None
    created_at: datetime
