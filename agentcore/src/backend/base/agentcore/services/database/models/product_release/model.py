from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, Date, DateTime, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class ProductRelease(SQLModel, table=True):  # type: ignore[call-arg]
    """Product release with SCD-style active window."""

    __tablename__ = "product_release"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    version: str = Field(sa_column=Column(String(50), nullable=False, unique=True, index=True))
    major: int = Field(nullable=False)
    minor: int = Field(nullable=False)
    patch: int = Field(nullable=False)
    release_notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    start_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    end_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    created_by: UUID | None = Field(default=None, nullable=True, foreign_key="user.id", index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("major", "minor", "patch", name="uq_product_release_semver"),
    )
