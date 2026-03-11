# Path: src/backend/agentcore/services/database/models/publish_record/model.py

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, Enum as SQLEnum, Text, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.user.model import User


class PublishStatusEnum(str, Enum):
    """Status of a published agent."""

    ACTIVE = "ACTIVE"
    UNPUBLISHED = "UNPUBLISHED"
    ERROR = "ERROR"
    PENDING = "PENDING"


class PublishRecordBase(SQLModel):
    """Base model for tracking agent publications to external platforms."""

    # Suppresses warnings during migrations
    __mapper_args__ = {"confirm_deleted_rows": False}

    agent_id: UUID = Field(foreign_key="agent.id", index=True, nullable=False)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    platform: str = Field(index=True, nullable=False, description="Target platform")
    platform_url: str = Field(nullable=False, description="Base URL of the target platform")
    external_id: str = Field(
        nullable=False, description="ID of the model/resource in the external platform"
    )
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    published_by: UUID = Field(foreign_key="user.id", nullable=False)
    status: PublishStatusEnum = Field(
        default=PublishStatusEnum.ACTIVE,
        sa_column=Column(
            SQLEnum(
                PublishStatusEnum,
                name="publish_status_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=text("'ACTIVE'"),
        ),
    )
    metadata_: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Additional platform-specific metadata",
        alias="metadata",
    )
    last_sync_at: datetime | None = Field(default=None, nullable=True)
    error_message: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Error message if status is ERROR",
    )


class PublishRecord(PublishRecordBase, table=True):  # type: ignore[call-arg]
    
    __tablename__ = "publish_record"

    # id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Relationships
    agent: Optional["Agent"] = Relationship(back_populates="publish_records")
    user: Optional["User"] = Relationship()

    __table_args__ = (
        # Ensure one active publication per agent per platform per URL
        UniqueConstraint(
            "agent_id",
            "platform",
            "platform_url",
            "status",
            name="unique_active_publication",
        ),
    )


class PublishRecordCreate(PublishRecordBase):
    """Model for creating a new publish record."""

    pass


class PublishRecordRead(BaseModel):
    """Model for reading publish record data."""

    id: UUID
    agent_id: UUID
    platform: str
    platform_url: str
    external_id: str
    published_at: datetime
    published_by: UUID
    status: PublishStatusEnum
    metadata_: dict | None = Field(None, alias="metadata")
    last_sync_at: datetime | None = None
    error_message: str | None = None


class PublishRecordUpdate(BaseModel):
    """Model for updating a publish record."""

    status: PublishStatusEnum | None = None
    metadata_: dict | None = Field(None, alias="metadata")
    last_sync_at: datetime | None = None
    error_message: str | None = None
