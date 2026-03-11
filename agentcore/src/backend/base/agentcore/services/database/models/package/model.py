from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Date, DateTime, String
from sqlmodel import Field, SQLModel


class Package(SQLModel, table=True):  # type: ignore[call-arg]
    """Cached snapshot of project dependencies, synced once at application startup."""

    __tablename__ = "package"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    version: str = Field(sa_column=Column(String(100), nullable=False))
    version_spec: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    package_type: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    release_id: UUID | None = Field(default=None, nullable=True, foreign_key="product_release.id", index=True)
    required_by: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    required_by_details: list[dict[str, str]] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    start_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    end_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    source: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    synced_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
