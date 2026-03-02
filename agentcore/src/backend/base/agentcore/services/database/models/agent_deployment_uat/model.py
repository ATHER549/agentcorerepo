# Path: src/backend/agentcore/services/database/models/agent_deployment_uat/model.py

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, Enum as SQLEnum, Index, Text, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.agent_bundle.model import AgentBundle
    from agentcore.services.database.models.department.model import Department
    from agentcore.services.database.models.organization.model import Organization
    from agentcore.services.database.models.user.model import User


class DeploymentUATStatusEnum(str, Enum):
    """Status of a UAT deployment."""

    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    ERROR = "ERROR"


class DeploymentVisibilityEnum(str, Enum):
    """Visibility level for a deployed agent."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class DeploymentLifecycleEnum(str, Enum):
    """Lifecycle step of a specific deployment version."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class AgentDeploymentUATBase(SQLModel):
    """Base model for UAT deployment records."""

    __mapper_args__ = {"confirm_deleted_rows": False}

    agent_id: UUID = Field(foreign_key="agent.id", index=True, nullable=False)
    org_id: UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    version_number: int = Field(nullable=False, description="Auto-increment per agent (v1, v2, v3)")
    agent_snapshot: dict = Field(
        sa_column=Column(JSON, nullable=False),
        description="Frozen copy of agent.data at publish time. Immutable.",
    )
    agent_name: str = Field(max_length=255, nullable=False, description="Name of the agent at publish time")
    agent_description: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Description of the agent at publish time",
    )
    publish_description: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Developer-provided description for this publish action",
    )
    is_active: bool = Field(
        default=True,
        nullable=False,
        description="Is this version currently running. Multiple can be true (shadow deploy).",
    )
    is_enabled: bool = Field(
        default=True,
        nullable=False,
        description="Admin kill switch. Can disable without deactivating.",
    )
    status: DeploymentUATStatusEnum = Field(
        default=DeploymentUATStatusEnum.PUBLISHED,
        sa_column=Column(
            SQLEnum(
                DeploymentUATStatusEnum,
                name="deployment_uat_status_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=text("'PUBLISHED'"),
        ),
    )
    lifecycle_step: DeploymentLifecycleEnum = Field(
        default=DeploymentLifecycleEnum.PUBLISHED,
        sa_column=Column(
            SQLEnum(
                DeploymentLifecycleEnum,
                name="deployment_lifecycle_enum",
                values_callable=lambda enum: [member.value for member in enum],
                create_constraint=False,
            ),
            nullable=False,
            server_default=text("'PUBLISHED'"),
        ),
        description="Deployment-level lifecycle: DRAFT / PUBLISHED / DEPRECATED / ARCHIVED",
    )
    visibility: DeploymentVisibilityEnum = Field(
        default=DeploymentVisibilityEnum.PRIVATE,
        sa_column=Column(
            SQLEnum(
                DeploymentVisibilityEnum,
                name="deployment_visibility_enum",
                values_callable=lambda enum: [member.value for member in enum],
                create_constraint=False,
            ),
            nullable=False,
            server_default=text("'PRIVATE'"),
        ),
    )
    deployed_by: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    deployed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    error_message: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Error message if status is ERROR",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AgentDeploymentUAT(AgentDeploymentUATBase, table=True):  # type: ignore[call-arg]

    __tablename__ = "agent_deployment_uat"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Relationships
    agent: Optional["Agent"] = Relationship(back_populates="deployment_uat_records")
    organization: Optional["Organization"] = Relationship()
    department: Optional["Department"] = Relationship()
    deployer: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AgentDeploymentUAT.deployed_by]"},
    )

    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_deployment_uat_agent_version"),
        Index("ix_deployment_uat_status", "status"),
        Index("ix_deployment_uat_agent_active", "agent_id", "is_active"),
        Index("ix_deployment_uat_org", "org_id"),
        Index("ix_deployment_uat_dept", "dept_id"),
        Index("ix_deployment_uat_lifecycle", "lifecycle_step"),
    )


class AgentDeploymentUATCreate(SQLModel):
    """Model for creating a new UAT deployment record."""

    agent_id: UUID
    org_id: UUID
    dept_id: UUID | None = None
    version_number: int
    agent_snapshot: dict
    agent_name: str
    agent_description: str | None = None
    publish_description: str | None = None
    deployed_by: UUID
    is_active: bool = True
    is_enabled: bool = True
    visibility: DeploymentVisibilityEnum = DeploymentVisibilityEnum.PRIVATE


class AgentDeploymentUATRead(BaseModel):
    """Model for reading UAT deployment data."""

    id: UUID
    agent_id: UUID
    org_id: UUID
    dept_id: UUID | None = None
    version_number: int
    agent_snapshot: dict
    agent_name: str
    agent_description: str | None = None
    publish_description: str | None = None
    is_active: bool
    is_enabled: bool
    status: DeploymentUATStatusEnum
    lifecycle_step: DeploymentLifecycleEnum
    visibility: DeploymentVisibilityEnum
    deployed_by: UUID
    deployed_at: datetime
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentDeploymentUATUpdate(BaseModel):
    """Model for updating a UAT deployment record."""

    is_active: bool | None = None
    is_enabled: bool | None = None
    status: DeploymentUATStatusEnum | None = None
    lifecycle_step: DeploymentLifecycleEnum | None = None
    visibility: DeploymentVisibilityEnum | None = None
    error_message: str | None = None
