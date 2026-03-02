# Path: src/backend/agentcore/services/database/models/agent_registry/model.py

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, Enum as SQLEnum, Float, Index, Integer, Text, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.organization.model import Organization
    from agentcore.services.database.models.user.model import User


class RegistryVisibilityEnum(str, Enum):
    """Visibility of a registry entry."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class RegistryDeploymentEnvEnum(str, Enum):
    """Environment discriminator for the deployment this registry entry points to."""

    UAT = "UAT"
    PROD = "PROD"


class AgentRegistryBase(SQLModel):
    """Base model for the agent registry (marketplace/catalog).

    Each row represents a discoverable, published agent that users can
    browse, search, and instantiate.

    The snapshot JSON is NOT stored here — it lives in the deployment table
    (agent_deployment_uat / agent_deployment_prod) and is fetched on clone.
    """

    __mapper_args__ = {"confirm_deleted_rows": False}

    org_id: UUID | None = Field(default=None, foreign_key="organization.id", index=True, nullable=True)
    agent_id: UUID = Field(foreign_key="agent.id", index=True, nullable=False)
    agent_deployment_id: UUID = Field(
        nullable=False,
        index=True,
        description="FK to agent_deployment_uat.id or agent_deployment_prod.id (polymorphic)",
    )
    deployment_env: RegistryDeploymentEnvEnum = Field(
        sa_column=Column(
            SQLEnum(
                RegistryDeploymentEnvEnum,
                name="registry_deployment_env_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
        ),
        description="Environment discriminator: UAT or PROD",
    )
    title: str = Field(max_length=255, nullable=False, description="Display title in the registry")
    summary: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Short summary / tagline for discovery",
    )
    tags: list | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Searchable tags for categorization (e.g. ['Chatbot', 'AI Agent'])",
    )
    rating: float | None = Field(
        default=None,
        sa_column=Column(Float, nullable=True),
        description="Average user rating (0.0 – 5.0), computed from agent_registry_rating table",
    )
    rating_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
        description="Number of ratings received (shown as '4.8 (1240)' in the UI)",
    )
    visibility: RegistryVisibilityEnum = Field(
        default=RegistryVisibilityEnum.PRIVATE,
        sa_column=Column(
            SQLEnum(
                RegistryVisibilityEnum,
                name="registry_visibility_enum",
                values_callable=lambda enum: [member.value for member in enum],
                create_constraint=False,
            ),
            nullable=False,
            server_default=text("'PRIVATE'"),
        ),
    )
    listed_by: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    listed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AgentRegistry(AgentRegistryBase, table=True):  # type: ignore[call-arg]

    __tablename__ = "agent_registry"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Relationships
    organization: Optional["Organization"] = Relationship()
    agent: Optional["Agent"] = Relationship()
    lister: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AgentRegistry.listed_by]"},
    )

    __table_args__ = (
        UniqueConstraint("agent_deployment_id", "deployment_env", name="uq_registry_deployment"),
        Index("ix_agent_registry_org", "org_id"),
        Index("ix_agent_registry_visibility", "visibility"),
        Index("ix_agent_registry_deployment", "agent_deployment_id", "deployment_env"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Per-user rating table — each user can rate a registry entry once
# ═══════════════════════════════════════════════════════════════════════════


class AgentRegistryRating(SQLModel, table=True):  # type: ignore[call-arg]
    """Stores individual user ratings for registry entries.

    Business rules:
        - Each user can rate a registry entry exactly once (upsert).
        - The average and count are denormalized onto AgentRegistry.rating
          and AgentRegistry.rating_count for fast browse queries.
    """

    __tablename__ = "agent_registry_rating"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    registry_id: UUID = Field(foreign_key="agent_registry.id", nullable=False)
    user_id: UUID = Field(foreign_key="user.id", nullable=False)
    score: float = Field(
        sa_column=Column(Float, nullable=False),
        description="Rating score (1.0 – 5.0)",
    )
    review: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Optional review text",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("registry_id", "user_id", name="uq_registry_rating_user"),
        Index("ix_registry_rating_org", "org_id"),
        Index("ix_registry_rating_dept", "dept_id"),
        Index("ix_registry_rating_registry", "registry_id"),
        Index("ix_registry_rating_user", "user_id"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# CRUD Schemas
# ═══════════════════════════════════════════════════════════════════════════


class AgentRegistryCreate(SQLModel):
    """Model for creating a new registry entry."""

    org_id: UUID | None = None
    agent_id: UUID
    agent_deployment_id: UUID
    deployment_env: RegistryDeploymentEnvEnum
    title: str
    summary: str | None = None
    tags: list | None = None
    visibility: RegistryVisibilityEnum = RegistryVisibilityEnum.PRIVATE
    listed_by: UUID


class AgentRegistryRead(BaseModel):
    """Model for reading registry data."""

    id: UUID
    org_id: UUID | None = None
    agent_id: UUID
    agent_deployment_id: UUID
    deployment_env: RegistryDeploymentEnvEnum
    title: str
    summary: str | None = None
    tags: list | None = None
    rating: float | None = None
    rating_count: int
    visibility: RegistryVisibilityEnum
    listed_by: UUID
    listed_at: datetime
    created_at: datetime
    updated_at: datetime


class AgentRegistryUpdate(BaseModel):
    """Model for updating a registry entry."""

    title: str | None = None
    summary: str | None = None
    tags: list | None = None
    rating: float | None = None
    rating_count: int | None = None
    visibility: RegistryVisibilityEnum | None = None
