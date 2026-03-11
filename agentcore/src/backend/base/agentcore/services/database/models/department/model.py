from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Enum as SQLEnum, String, Text, UniqueConstraint, text
from sqlmodel import Field, SQLModel


class DeptStatusEnum(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Department(SQLModel, table=True):  # type: ignore[call-arg]
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    code: str | None = Field(default=None, sa_column=Column(String(50), nullable=True))
    parent_dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    admin_user_id: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    status: DeptStatusEnum = Field(
        default=DeptStatusEnum.ACTIVE,
        sa_column=Column(
            SQLEnum(
                DeptStatusEnum,
                name="dept_status_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=text("'active'"),
        ),
    )
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
        UniqueConstraint("org_id", "id", name="uq_department_org_id_id"),
        UniqueConstraint("org_id", "name", name="uq_department_org_name"),
    )
