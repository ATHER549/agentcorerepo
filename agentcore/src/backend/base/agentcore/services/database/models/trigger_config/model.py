from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, Column, DateTime, Enum as SQLEnum, Index, Text, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.user.model import User


class TriggerTypeEnum(str, Enum):
    """Type of trigger."""

    SCHEDULE = "schedule"
    FOLDER_MONITOR = "folder_monitor"
    EMAIL_MONITOR = "email_monitor"


class TriggerExecutionStatusEnum(str, Enum):
    """Status of a trigger execution."""

    STARTED = "started"
    SUCCESS = "success"
    ERROR = "error"


# ── TriggerConfig ──────────────────────────────────────────────────────────


class TriggerConfigBase(SQLModel):
    """Base model for trigger configuration."""

    __mapper_args__ = {"confirm_deleted_rows": False}

    agent_id: UUID = Field(foreign_key="agent.id", index=True, nullable=False)
    deployment_id: UUID | None = Field(
        default=None,
        nullable=True,
        index=True,
        description="Associated deployment ID (UAT or PROD).",
    )
    trigger_type: TriggerTypeEnum = Field(
        sa_column=Column(
            SQLEnum(
                TriggerTypeEnum,
                name="trigger_type_enum",
                values_callable=lambda enum: [m.value for m in enum],
            ),
            nullable=False,
        ),
    )
    trigger_config: dict = Field(
        sa_column=Column(JSON, nullable=False),
        description="Type-specific configuration (cron, folder path, etc.).",
    )
    is_active: bool = Field(default=True, nullable=False)
    environment: str = Field(
        max_length=10,
        nullable=False,
        default="dev",
        description="Environment: dev, uat, or prod.",
    )
    version: str | None = Field(
        default=None,
        max_length=20,
        nullable=True,
        description="Deployment version (e.g. 'v1').",
    )
    last_triggered_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    trigger_count: int = Field(default=0, nullable=False)
    created_by: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )

    class Config:
        arbitrary_types_allowed = True


class TriggerConfigTable(TriggerConfigBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "trigger_config"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Relationships
    agent: Optional["Agent"] = Relationship()
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[TriggerConfigTable.created_by]"},
    )

    __table_args__ = (
        Index("ix_trigger_config_agent", "agent_id"),
        Index("ix_trigger_config_type", "trigger_type"),
        Index("ix_trigger_config_active", "is_active"),
        Index("ix_trigger_config_env", "environment"),
    )


class TriggerConfigCreate(SQLModel):
    """Model for creating a new trigger config."""

    agent_id: UUID
    deployment_id: UUID | None = None
    trigger_type: TriggerTypeEnum
    trigger_config: dict
    is_active: bool = True
    environment: str = "dev"
    version: str | None = None
    created_by: UUID


class TriggerConfigRead(BaseModel):
    """Model for reading trigger config data."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    deployment_id: UUID | None = None
    trigger_type: TriggerTypeEnum
    trigger_config: dict
    is_active: bool
    environment: str
    version: str | None = None
    last_triggered_at: datetime | None = None
    trigger_count: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class TriggerConfigUpdate(BaseModel):
    """Model for updating a trigger config."""

    trigger_config: dict | None = None
    is_active: bool | None = None
    deployment_id: UUID | None = None
    version: str | None = None


# ── TriggerExecutionLog ────────────────────────────────────────────────────


class TriggerExecutionLogBase(SQLModel):
    """Base model for trigger execution log."""

    trigger_config_id: UUID = Field(foreign_key="trigger_config.id", index=True, nullable=False)
    agent_id: UUID = Field(nullable=False, index=True)
    triggered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )
    status: TriggerExecutionStatusEnum = Field(
        sa_column=Column(
            SQLEnum(
                TriggerExecutionStatusEnum,
                name="trigger_execution_status_enum",
                values_callable=lambda enum: [m.value for m in enum],
            ),
            nullable=False,
        ),
    )
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    execution_duration_ms: int | None = Field(default=None, nullable=True)
    payload: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    class Config:
        arbitrary_types_allowed = True


class TriggerExecutionLogTable(TriggerExecutionLogBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "trigger_execution_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    __table_args__ = (
        Index("ix_trigger_exec_config", "trigger_config_id"),
        Index("ix_trigger_exec_agent", "agent_id"),
        Index("ix_trigger_exec_status", "status"),
        Index("ix_trigger_exec_triggered_at", "triggered_at"),
    )


class TriggerExecutionLogRead(BaseModel):
    """Model for reading trigger execution log data."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trigger_config_id: UUID
    agent_id: UUID
    triggered_at: datetime
    status: TriggerExecutionStatusEnum
    error_message: str | None = None
    execution_duration_ms: int | None = None
    payload: dict | None = None