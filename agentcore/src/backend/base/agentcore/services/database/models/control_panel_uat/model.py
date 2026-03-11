from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Index, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent
    from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT
    from agentcore.services.database.models.department.model import Department
    from agentcore.services.database.models.organization.model import Organization
    from agentcore.services.database.models.user.model import User


class ControlPanelUATBase(SQLModel):
    __mapper_args__ = {"confirm_deleted_rows": False}

    deployment_id: UUID = Field(foreign_key="agent_deployment_uat.id", nullable=False, index=True)
    agent_id: UUID = Field(foreign_key="agent.id", nullable=False, index=True)
    org_id: UUID = Field(foreign_key="organization.id", nullable=False, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    status: str = Field(default="PUBLISHED", max_length=50, nullable=False, description="Control panel status")
    notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ControlPanelUAT(ControlPanelUATBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "control_panel_uat"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    deployment: Optional["AgentDeploymentUAT"] = Relationship()
    agent: Optional["Agent"] = Relationship()
    organization: Optional["Organization"] = Relationship()
    department: Optional["Department"] = Relationship()
    creator: Optional["User"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[ControlPanelUAT.created_by]"})
    updater: Optional["User"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[ControlPanelUAT.updated_by]"})

    __table_args__ = (
        UniqueConstraint("deployment_id", name="uq_control_panel_uat_deployment"),
        Index("ix_control_panel_uat_org_dept", "org_id", "dept_id"),
    )


class ControlPanelUATCreate(SQLModel):
    deployment_id: UUID
    agent_id: UUID
    org_id: UUID
    dept_id: UUID | None = None
    status: str = "PUBLISHED"
    notes: str | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None


class ControlPanelUATRead(BaseModel):
    id: UUID
    deployment_id: UUID
    agent_id: UUID
    org_id: UUID
    dept_id: UUID | None = None
    status: str
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_by: UUID | None = None
    updated_at: datetime


class ControlPanelUATUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    updated_by: UUID | None = None
