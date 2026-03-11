from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, Text
from sqlmodel import Field, SQLModel


class ObservabilityProvisionJob(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "observability_provision_job"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    idempotency_key: str = Field(sa_column=Column(String(255), nullable=False, unique=True, index=True))
    scope_type: str = Field(sa_column=Column(String(32), nullable=False))
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)

    status: str = Field(default="pending", sa_column=Column(String(32), nullable=False, index=True))
    payload_hash: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    retry_count: int = Field(default=0)
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    created_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
