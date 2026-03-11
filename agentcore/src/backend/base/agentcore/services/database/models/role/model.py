from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class Role(SQLModel, table=True):  # type: ignore[call-arg]
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, max_length=100)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, sa_column=Column(Text))
    parent_role_id: UUID | None = Field(default=None, foreign_key="role.id", nullable=True)
    is_system: bool = Field(default=False)
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
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

    __table_args__ = (UniqueConstraint("name", name="uq_role_name"),)


class RoleCreate(SQLModel):
    name: str
    display_name: str | None = None
    description: str | None = None


class RoleUpdate(SQLModel):
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    parent_role_id: UUID | None = None
    is_active: bool | None = None


class RoleRead(SQLModel):
    id: UUID
    name: str
    display_name: str | None = None
    description: str | None = None
    parent_role_id: UUID | None = None
    is_system: bool
    is_active: bool = True
