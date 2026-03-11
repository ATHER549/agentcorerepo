from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text, text
from sqlmodel import Field, SQLModel


class LangfuseBinding(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "langfuse_binding"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    scope_type: str = Field(
        default="department",
        sa_column=Column(String(32), nullable=False),
        description="department or org_admin",
    )

    langfuse_org_id: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    langfuse_project_id: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    langfuse_project_name: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    langfuse_host: str = Field(sa_column=Column(String(512), nullable=False))

    public_key_encrypted: str = Field(sa_column=Column(Text, nullable=False))
    secret_key_encrypted: str = Field(sa_column=Column(Text, nullable=False))

    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )

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

    __table_args__ = (
        Index(
            "ix_langfuse_binding_active_org_admin",
            "org_id",
            unique=True,
            postgresql_where=text("scope_type = 'org_admin' AND is_active = true"),
        ),
        Index(
            "ix_langfuse_binding_active_department",
            "dept_id",
            unique=True,
            postgresql_where=text("scope_type = 'department' AND dept_id IS NOT NULL AND is_active = true"),
        ),
    )
