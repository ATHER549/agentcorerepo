from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, DateTime, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class Package(SQLModel, table=True):  # type: ignore[call-arg]
    """Cached snapshot of project dependencies, synced once at application startup."""

    __tablename__ = "package"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    version: str = Field(sa_column=Column(String(100), nullable=False))
    version_spec: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    package_type: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    required_by: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    source: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    synced_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("name", "package_type", name="uq_package_name_type"),
    )
