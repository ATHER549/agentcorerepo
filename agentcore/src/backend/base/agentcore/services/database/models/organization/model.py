from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Index, String, Text, text
from sqlmodel import Field, SQLModel


class OrgTierEnum(str, Enum):
    FREE = "free"
    STANDARD = "standard"
    ENTERPRISE = "enterprise"


class OrgStatusEnum(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class Organization(SQLModel, table=True):  # type: ignore[call-arg]
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    tier: OrgTierEnum = Field(
        default=OrgTierEnum.STANDARD,
        sa_column=Column(
            SQLEnum(
                OrgTierEnum,
                name="org_tier_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=text("'standard'"),
        ),
    )
    status: OrgStatusEnum = Field(
        default=OrgStatusEnum.ACTIVE,
        sa_column=Column(
            SQLEnum(
                OrgStatusEnum,
                name="org_status_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=text("'active'"),
        ),
    )
    owner_user_id: UUID = Field(foreign_key="user.id", nullable=False)
    created_by: UUID = Field(foreign_key="user.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(), nullable=False),
    )
    updated_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(), nullable=False),
    )

    __table_args__ = (
        Index("ix_organization_name", "name", unique=True),
    )
