from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlmodel import Field, SQLModel


class ConnectorCatalogue(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "connector_catalogue"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)

    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    provider: str = Field(sa_column=Column(String(50), nullable=False, index=True))  # postgresql, oracle, sqlserver, mysql, azure_blob, sharepoint
    # DB-only fields — nullable so Azure Blob / SharePoint connectors can omit them
    host: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    port: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    database_name: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    schema_name: str | None = Field(default="public", sa_column=Column(String(255), nullable=True))
    username: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    password_encrypted: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    ssl_enabled: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    # Provider-specific config for non-DB connectors (Azure Blob, SharePoint, etc.)
    provider_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    visibility: str = Field(
        default="private",
        sa_column=Column(String(20), nullable=False, default="private"),
    )
    public_scope: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))  # organization | department
    shared_user_ids: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    public_dept_ids: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    status: str = Field(sa_column=Column(String(50), nullable=False, default="disconnected"))  # connected, disconnected, error
    tables_metadata: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))  # cached schema info
    last_tested_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    is_custom: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))

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
    published_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    published_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    __table_args__ = (
        CheckConstraint("(dept_id IS NULL) OR (org_id IS NOT NULL)", name="ck_connector_scope_consistency"),
        ForeignKeyConstraint(
            ["org_id", "dept_id"],
            ["department.org_id", "department.id"],
            name="fk_connector_org_dept_department",
        ),
        UniqueConstraint("org_id", "dept_id", "name", name="uq_connector_catalogue_scope_name"),
        Index("ix_connector_catalogue_org_dept", "org_id", "dept_id"),
    )
