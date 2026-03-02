
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, Relationship, SQLModel

from agentcore.schema.serialize import UUIDstr

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.project.model import Project


class UserOptin(BaseModel):
    github_starred: bool = Field(default=False)
    dialog_dismissed: bool = Field(default=False)
    discord_clicked: bool = Field(default=False)
    # Add more opt-in actions as needed


class User(SQLModel, table=True):  # type: ignore[call-arg]
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username: str = Field(index=True, unique=True)
    email: str | None = Field(default=None, nullable=True, index=True, unique=True)
    display_name: str | None = Field(default=None, nullable=True)
    entra_object_id: str | None = Field(default=None, nullable=True, index=True, unique=True)
    password: str = Field()
    profile_image: str | None = Field(default=None, nullable=True)
    is_active: bool = Field(default=False)
    is_superuser: bool = Field(default=False)
    role: str = Field(default="developer", max_length=50)
    creator_email: str | None = Field(default=None, nullable=True)
    creator_role: str | None = Field(default=None, nullable=True, max_length=50)
    department_admin_email: str | None = Field(default=None, nullable=True)
    department_name: str | None = Field(default=None, nullable=True)
    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: datetime | None = Field(default=None, nullable=True)
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    store_api_key: str | None = Field(default=None, nullable=True)
    department_name: str | None = Field(default=None, nullable=True, max_length=255, index=True)
    department_admin: UUID | None = Field(
        default=None, nullable=True, foreign_key="user.id",
        description="FK to the department admin user",
    )
    created_by: UUID | None = Field(
        default=None, nullable=True, foreign_key="user.id",
        description="FK to the user who created this account",
    )
    country: str | None = Field(default=None, nullable=True, max_length=100, index=True)
    agents: list["Agent"] = Relationship(back_populates="user")
    # [VARIABLE REMOVED] variables relationship removed — migrating to Azure Key Vault
    folders: list["Project"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "delete", "foreign_keys": "Project.user_id"},
    )
    optins: dict[str, Any] | None = Field(
        sa_column=Column(JSON, default=lambda: UserOptin().model_dump(), nullable=True)
    )


class UserCreate(SQLModel):
    username: str = Field()
    email: str | None = None
    display_name: str | None = None
    password: str | None = None
    role: str = Field(default="developer", max_length=50)
    department_admin_email: str | None = None
    department_name: str | None = None
    department_id: UUID | None = None
    organization_name: str | None = None
    organization_description: str | None = None
    optins: dict[str, Any] | None = Field(
        default={"github_starred": False, "dialog_dismissed": False, "discord_clicked": False}
    )
    department_name: str | None = None
    department_admin: UUID | None = None
    created_by: UUID | None = None
    country: str | None = None

class UserRead(SQLModel):
    id: UUID = Field(default_factory=uuid4)
    username: str = Field()
    email: str | None = Field(default=None)
    display_name: str | None = Field(default=None)
    entra_object_id: str | None = Field(default=None)
    profile_image: str | None = Field()
    store_api_key: str | None = Field(nullable=True)
    is_active: bool = Field()
    is_superuser: bool = Field()
    role: str = Field()
    creator_email: str | None = Field(default=None)
    creator_role: str | None = Field(default=None)
    department_admin_email: str | None = Field(default=None)
    department_name: str | None = Field(default=None)
    create_at: datetime = Field()
    updated_at: datetime = Field()
    last_login_at: datetime | None = Field(nullable=True)
    deleted_at: datetime | None = Field(default=None)
    optins: dict[str, Any] | None = Field(default=None)
    department_name: str | None = Field(default=None)
    department_admin: UUID | None = Field(default=None)
    created_by: UUID | None = Field(default=None)
    created_by_username: str | None = Field(default=None)
    country: str | None = Field(default=None)
    organization_name: str | None = Field(default=None)


class UserUpdate(SQLModel):
    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    entra_object_id: str | None = None
    profile_image: str | None = None
    password: str | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    role: str | None = None
    creator_email: str | None = None
    creator_role: str | None = None
    department_admin_email: str | None = None
    department_name: str | None = None
    last_login_at: datetime | None = None
    deleted_at: datetime | None = None
    optins: dict[str, Any] | None = None
    department_name: str | None = None
    department_admin: UUID | None = None
    created_by: UUID | None = None
    country: str | None = None
