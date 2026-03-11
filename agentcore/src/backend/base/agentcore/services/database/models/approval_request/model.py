# Path: src/backend/agentcore/services/database/models/approval_request/model.py

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, Enum as SQLEnum, ForeignKey, Index, Text, Uuid, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd
    from agentcore.services.database.models.user.model import User

from agentcore.services.database.models.agent_deployment_prod.model import ProdDeploymentVisibilityEnum


class ApprovalDecisionEnum(str, Enum):
    """Decision outcome for an approval request."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalRequestBase(SQLModel):
    """Base model for approval requests."""

    __mapper_args__ = {"confirm_deleted_rows": False}

    agent_id: UUID = Field(foreign_key="agent.id", nullable=False, description="The agent being published")
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    deployment_id: UUID = Field(
        sa_column=Column(
            Uuid(),
            ForeignKey("agent_deployment_prod.id", use_alter=True, name="fk_approval_deployment_id"),
            nullable=False,
        ),
        description="FK to the agent_deployment_prod record awaiting approval",
    )
    requested_by: UUID = Field(
        foreign_key="user.id",
        nullable=False,
        description="User who requested the publish",
    )
    request_to: UUID = Field(
        foreign_key="user.id",
        nullable=False,
        description="Admin/approver the request is sent to",
    )
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reviewed_at: datetime | None = Field(default=None, nullable=True)
    decision: ApprovalDecisionEnum | None = Field(
        default=None,
        sa_column=Column(
            SQLEnum(
                ApprovalDecisionEnum,
                name="approval_decision_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=True,
        ),
    )
    justification: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Reviewer comments / reason for decision",
    )
    visibility_requested: ProdDeploymentVisibilityEnum = Field(
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
    publish_description: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Developer-provided description for this publish",
    )
    file_path: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Attachment references for the approval request (e.g. supporting docs, screenshots)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ApprovalRequest(ApprovalRequestBase, table=True):  # type: ignore[call-arg]

    __tablename__ = "approval_request"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Relationships
    agent: Optional["Agent"] = Relationship()
    requester: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[ApprovalRequest.requested_by]"},
    )
    approver: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[ApprovalRequest.request_to]"},
    )
    deployment_prod_record: Optional["AgentDeploymentProd"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[ApprovalRequest.deployment_id]"},
    )

    __table_args__ = (
        Index("ix_approval_deployment_id", "deployment_id"),
        Index("ix_approval_org", "org_id"),
        Index("ix_approval_dept", "dept_id"),
        Index("ix_approval_request_to_decision", "request_to", "decision"),
        Index("ix_approval_requested_by_decision", "requested_by", "decision"),
    )


class ApprovalRequestCreate(SQLModel):
    """Model for creating a new approval request."""

    agent_id: UUID
    deployment_id: UUID
    requested_by: UUID
    request_to: UUID
    visibility_requested: ProdDeploymentVisibilityEnum = ProdDeploymentVisibilityEnum.PRIVATE
    publish_description: str | None = None
    file_path: dict | None = None


class ApprovalRequestRead(BaseModel):
    """Model for reading approval request data."""

    id: UUID
    agent_id: UUID
    org_id: UUID | None = None
    dept_id: UUID | None = None
    deployment_id: UUID
    requested_by: UUID
    request_to: UUID
    requested_at: datetime
    reviewed_at: datetime | None = None
    decision: ApprovalDecisionEnum | None = None
    justification: str | None = None
    visibility_requested: ProdDeploymentVisibilityEnum
    publish_description: str | None = None
    file_path: dict | None = None
    created_at: datetime
    updated_at: datetime


class ApprovalRequestUpdate(BaseModel):
    """Model for updating an approval request (review action)."""

    reviewed_at: datetime | None = None
    decision: ApprovalDecisionEnum | None = None
    justification: str | None = None
    file_path: dict | None = None
