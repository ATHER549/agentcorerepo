from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import text
from sqlmodel import Field, SQLModel


class KBVisibilityEnum(str, Enum):
    PRIVATE = "PRIVATE"
    DEPARTMENT = "DEPARTMENT"
    ORGANIZATION = "ORGANIZATION"


class KnowledgeBase(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "knowledge_base"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    created_by: UUID = Field(foreign_key="user.id", nullable=False)
    visibility: KBVisibilityEnum = Field(
        default=KBVisibilityEnum.PRIVATE,
        sa_column=Column(
            SQLEnum(
                KBVisibilityEnum,
                name="kb_visibility_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=text("'PRIVATE'"),
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("org_id", "dept_id", "name", name="uq_kb_org_dept_name"),
        Index("ix_knowledge_base_org_id", "org_id"),
        Index("ix_knowledge_base_dept_id", "dept_id"),
        Index("ix_knowledge_base_created_by", "created_by"),
        Index("ix_knowledge_base_visibility", "visibility"),
    )
