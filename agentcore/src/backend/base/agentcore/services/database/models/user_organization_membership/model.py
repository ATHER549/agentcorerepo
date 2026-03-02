from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Index, String, UniqueConstraint
from sqlmodel import Field, SQLModel


class UserOrganizationMembership(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "user_organization_membership"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", nullable=False)
    org_id: UUID = Field(foreign_key="organization.id", nullable=False)
    status: str = Field(default="invited", sa_column=Column(String(50), nullable=False))
    role_id: UUID = Field(foreign_key="role.id", nullable=False)
    invited_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    accepted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_uom_user_org"),
        Index("ix_uom_user_id", "user_id"),
        Index("ix_uom_org_id", "org_id"),
        Index("ix_uom_role_id", "role_id"),
    )
