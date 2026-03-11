# Path: src/backend/agentcore/services/database/models/agent_bundle/model.py

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, Enum as SQLEnum, Index, Text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.user.model import User


class BundleTypeEnum(str, Enum):
    """Type of bundled resource attached to a deployment."""

    MODEL = "model"
    MCP_SERVER = "mcp_server"
    GUARDRAIL = "guardrail"
    KNOWLEDGE_BASE = "knowledge_base"
    VECTOR_DB = "vector_db"
    CONNECTOR = "connector"
    TOOL = "tool"
    CUSTOM_COMPONENT = "custom_component"


class DeploymentEnvEnum(str, Enum):
    """Which environment the bundle belongs to."""

    UAT = "UAT"
    PROD = "PROD"


class AgentBundleBase(SQLModel):
    """Base model for agent bundle records.

    An agent_bundle row captures a pinned external resource
    (model, MCP server, guardrail) that is part of a specific deployment.
    """

    __mapper_args__ = {"confirm_deleted_rows": False}

    agent_id: UUID = Field(foreign_key="agent.id", index=True, nullable=False)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    deployment_id: UUID = Field(
        nullable=False,
        index=True,
        description="FK to either agent_deployment_uat.id or agent_deployment_prod.id (polymorphic)",
    )
    deployment_env: DeploymentEnvEnum = Field(
        sa_column=Column(
            SQLEnum(
                DeploymentEnvEnum,
                name="deployment_env_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
        ),
        description="Discriminator: UAT or PROD",
    )
    bundle_type: BundleTypeEnum = Field(
        sa_column=Column(
            SQLEnum(
                BundleTypeEnum,
                name="bundle_type_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
        ),
    )
    resource_name: str = Field(
        max_length=255,
        nullable=False,
        description="Human-readable name of the bundled resource (e.g. 'gpt-4o', 'content-filter-v2')",
    )
    resource_config: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Frozen config / version pin for the resource at deploy time",
    )
    notes: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Optional notes about this bundle entry",
    )
    created_by: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AgentBundle(AgentBundleBase, table=True):  # type: ignore[call-arg]

    __tablename__ = "agent_bundle"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Relationships
    agent: Optional["Agent"] = Relationship()
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[AgentBundle.created_by]"},
    )

    __table_args__ = (
        Index("ix_agent_bundle_deployment", "deployment_id", "deployment_env"),
        Index("ix_agent_bundle_org", "org_id"),
        Index("ix_agent_bundle_dept", "dept_id"),
        Index("ix_agent_bundle_type", "bundle_type"),
        Index("ix_agent_bundle_agent", "agent_id"),
    )


class AgentBundleCreate(SQLModel):
    """Model for creating a new agent bundle record."""

    agent_id: UUID
    deployment_id: UUID
    deployment_env: DeploymentEnvEnum
    bundle_type: BundleTypeEnum
    resource_name: str
    resource_config: dict | None = None
    notes: str | None = None
    created_by: UUID


class AgentBundleRead(BaseModel):
    """Model for reading agent bundle data."""

    id: UUID
    agent_id: UUID
    org_id: UUID | None = None
    dept_id: UUID | None = None
    deployment_id: UUID
    deployment_env: DeploymentEnvEnum
    bundle_type: BundleTypeEnum
    resource_name: str
    resource_config: dict | None = None
    notes: str | None = None
    created_by: UUID
    created_at: datetime


class AgentBundleUpdate(BaseModel):
    """Model for updating an agent bundle record."""

    resource_name: str | None = None
    resource_config: dict | None = None
    notes: str | None = None
