# Path: src/backend/agentcore/services/database/models/agent_deployment_prod/model.py

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, Enum as SQLEnum, Index, Text, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT
    from agentcore.services.database.models.approval_request.model import ApprovalRequest
    from agentcore.services.database.models.department.model import Department
    from agentcore.services.database.models.organization.model import Organization
    from agentcore.services.database.models.user.model import User


class DeploymentPRODStatusEnum(str, Enum):
    """Status of a PROD deployment."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    ERROR = "ERROR"


class ProdDeploymentVisibilityEnum(str, Enum):
    """Visibility level for a deployed agent in PROD."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class ProdDeploymentLifecycleEnum(str, Enum):
    """Lifecycle step of a PROD deployment version."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class AgentDeploymentProdBase(SQLModel):
    """Base model for PROD deployment records."""

    __mapper_args__ = {"confirm_deleted_rows": False}

    agent_id: UUID = Field(foreign_key="agent.id", index=True, nullable=False)
    org_id: UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    promoted_from_uat_id: UUID | None = Field(
        default=None,
        foreign_key="agent_deployment_uat.id",
        nullable=True,
        index=True,
        description="Reference to the UAT deployment this was promoted from",
    )
    approval_id: UUID | None = Field(
        default=None,
        foreign_key="approval_request.id",
        nullable=True,
        index=True,
        description="Reference to the approval request that authorized this deployment",
    )
    version_number: int = Field(nullable=False, description="Production-specific version number")
    agent_snapshot: dict = Field(
        sa_column=Column(JSON, nullable=False),
        description="Frozen copy of agent.data at promotion time. Immutable.",
    )
    agent_name: str = Field(max_length=255, nullable=False, description="Name of the agent at promotion time")
    agent_description: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Description of the agent at promotion time",
    )
    publish_description: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Developer-provided description for this promotion",
    )
    is_active: bool = Field(
        default=False,
        nullable=False,
        description="Is this version currently running. Default false until approved.",
    )
    is_enabled: bool = Field(
        default=True,
        nullable=False,
        description="Admin kill switch. Can disable without deactivating.",
    )
    status: DeploymentPRODStatusEnum = Field(
        default=DeploymentPRODStatusEnum.PENDING_APPROVAL,
        sa_column=Column(
            SQLEnum(
                DeploymentPRODStatusEnum,
                name="deployment_prod_status_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=text("'PENDING_APPROVAL'"),
        ),
    )
    lifecycle_step: ProdDeploymentLifecycleEnum = Field(
        default=ProdDeploymentLifecycleEnum.DRAFT,
        sa_column=Column(
            SQLEnum(
                ProdDeploymentLifecycleEnum,
                name="prod_deployment_lifecycle_enum",
                values_callable=lambda enum: [member.value for member in enum],
                create_constraint=False,
            ),
            nullable=False,
            server_default=text("'DRAFT'"),
        ),
        description="Deployment-level lifecycle: DRAFT / PUBLISHED / DEPRECATED / ARCHIVED",
    )
    visibility: ProdDeploymentVisibilityEnum = Field(
        default=ProdDeploymentVisibilityEnum.PRIVATE,
        sa_column=Column(
            SQLEnum(
                ProdDeploymentVisibilityEnum,
                name="prod_deployment_visibility_enum",
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


class AgentDeploymentProd(AgentDeploymentProdBase, table=True):  # type: ignore[call-arg]

    __tablename__ = "agent_deployment_prod"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Relationships
    agent: Optional["Agent"] = Relationship(back_populates="deployment_prod_records")
    organization: Optional["Organization"] = Relationship()
    department: Optional["Department"] = Relationship()
    promoted_from_uat: Optional["AgentDeploymentUAT"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AgentDeploymentProd.promoted_from_uat_id]"},
    )
    approval: Optional["ApprovalRequest"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AgentDeploymentProd.approval_id]"},
    )
    deployer: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AgentDeploymentProd.deployed_by]"},
    )

    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_deployment_prod_agent_version"),
        Index("ix_deployment_prod_status", "status"),
        Index("ix_deployment_prod_agent_active", "agent_id", "is_active"),
        Index("ix_deployment_prod_org", "org_id"),
        Index("ix_deployment_prod_dept", "dept_id"),
        Index("ix_deployment_prod_lifecycle", "lifecycle_step"),
        Index("ix_deployment_prod_approval", "approval_id"),
    )


class AgentDeploymentProdCreate(SQLModel):
    """Model for creating a new PROD deployment record."""

    agent_id: UUID
    org_id: UUID
    dept_id: UUID | None = None
    promoted_from_uat_id: UUID | None = None
    version_number: int
    agent_snapshot: dict
    agent_name: str
    agent_description: str | None = None
    publish_description: str | None = None
    deployed_by: UUID
    is_active: bool = False
    is_enabled: bool = True
    visibility: ProdDeploymentVisibilityEnum = ProdDeploymentVisibilityEnum.PRIVATE


class AgentDeploymentProdRead(BaseModel):
    """Model for reading PROD deployment data."""

    id: UUID
    agent_id: UUID
    org_id: UUID
    dept_id: UUID | None = None
    promoted_from_uat_id: UUID | None = None
    approval_id: UUID | None = None
    version_number: int
    agent_snapshot: dict
    agent_name: str
    agent_description: str | None = None
    publish_description: str | None = None
    is_active: bool
    is_enabled: bool
    status: DeploymentPRODStatusEnum
    lifecycle_step: ProdDeploymentLifecycleEnum
    visibility: ProdDeploymentVisibilityEnum
    deployed_by: UUID
    deployed_at: datetime
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentDeploymentProdUpdate(BaseModel):
    """Model for updating a PROD deployment record."""

    is_active: bool | None = None
    is_enabled: bool | None = None
    status: DeploymentPRODStatusEnum | None = None
    lifecycle_step: ProdDeploymentLifecycleEnum | None = None
    visibility: ProdDeploymentVisibilityEnum | None = None
    approval_id: UUID | None = None
    error_message: str | None = None
