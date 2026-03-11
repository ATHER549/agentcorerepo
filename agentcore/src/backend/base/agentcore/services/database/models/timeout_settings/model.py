from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class TimeoutSettings(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "timeout_settings"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    setting_key: str = Field(sa_column=Column(String(100), nullable=False, index=True))
    label: str = Field(sa_column=Column(String(255), nullable=False))
    value: str | None = Field(default=None, sa_column=Column(String(100), nullable=True))
    unit: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    units: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    setting_type: str = Field(sa_column=Column(String(20), nullable=False))
    checked: bool | None = Field(default=None, sa_column=Column(Boolean, nullable=True))
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

    __table_args__ = (UniqueConstraint("setting_key", name="uq_timeout_settings_setting_key"),)
