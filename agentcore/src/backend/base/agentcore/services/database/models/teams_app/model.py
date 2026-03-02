# Path: src/backend/base/agentcore/services/database/models/teams_app/model.py

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, Enum as SQLEnum, Text, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.user.model import User


class TeamsPublishStatusEnum(str, Enum):
    """Status of a Teams app publication."""

    DRAFT = "DRAFT"
    UPLOADED = "UPLOADED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    UNPUBLISHED = "UNPUBLISHED"


class TeamsAppBase(SQLModel):
    """Base model for tracking Teams app publications."""

    __mapper_args__ = {"confirm_deleted_rows": False}

    agent_id: UUID = Field(foreign_key="agent.id", index=True, nullable=False)
    teams_app_external_id: str | None = Field(
        default=None,
        nullable=True,
        description="The ID assigned by Microsoft Graph after upload to the app catalog",
    )
    bot_app_id: str = Field(
        nullable=False,
        description="The Azure AD App ID of the bot registration used for this app",
    )
    bot_app_secret: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="The Azure AD App Secret for per-agent bot registration",
    )
    manifest_version: str = Field(default="1.0.0", nullable=False)
    display_name: str = Field(nullable=False)
    short_description: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    status: TeamsPublishStatusEnum = Field(
        default=TeamsPublishStatusEnum.DRAFT,
        sa_column=Column(
            SQLEnum(
                TeamsPublishStatusEnum,
                name="teams_publish_status_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=text("'DRAFT'"),
        ),
    )
    published_by: UUID = Field(foreign_key="user.id", nullable=False)
    published_at: datetime | None = Field(default=None, nullable=True)
    last_error: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    manifest_data: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="The generated Teams manifest JSON",
    )


class TeamsApp(TeamsAppBase, table=True):  # type: ignore[call-arg]

    __tablename__ = "teams_app"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent: Optional["Agent"] = Relationship()
    user: Optional["User"] = Relationship()
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class TeamsAppCreate(TeamsAppBase):
    """Model for creating a new Teams app record."""


class TeamsAppRead(BaseModel):
    """Model for reading Teams app data."""

    id: UUID
    agent_id: UUID
    teams_app_external_id: str | None = None
    bot_app_id: str
    manifest_version: str
    display_name: str
    short_description: str | None = None
    status: TeamsPublishStatusEnum
    published_by: UUID
    published_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class TeamsAppUpdate(BaseModel):
    """Model for updating a Teams app record."""

    teams_app_external_id: str | None = None
    manifest_version: str | None = None
    display_name: str | None = None
    short_description: str | None = None
    status: TeamsPublishStatusEnum | None = None
    published_at: datetime | None = None
    last_error: str | None = None
    manifest_data: dict | None = None
