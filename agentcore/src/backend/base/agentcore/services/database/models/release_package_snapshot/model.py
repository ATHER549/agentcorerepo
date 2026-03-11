from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, DateTime, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class ReleasePackageSnapshot(SQLModel, table=True):  # type: ignore[call-arg]
    """Package snapshot captured at release creation time."""

    __tablename__ = "release_package_snapshot"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    release_id: UUID = Field(nullable=False, foreign_key="product_release.id", index=True)
    name: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    version: str = Field(sa_column=Column(String(100), nullable=False))
    version_spec: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    package_type: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    required_by: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    source: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "name",
            "package_type",
            name="uq_release_package_snapshot_release_name_type",
        ),
    )
