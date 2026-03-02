from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, Index, String, Text, text
from sqlmodel import Field, SQLModel

from agentcore.services.database.models.approval_request.model import ApprovalDecisionEnum
from agentcore.services.database.models.model_registry.model import ModelEnvironment, ModelVisibilityScope


class ModelApprovalRequestType(str, Enum):
    CREATE = "create"
    PROMOTE = "promote"
    VISIBILITY = "visibility"


class ModelApprovalRequestBase(SQLModel):
    model_id: UUID = Field(foreign_key="model_registry.id", nullable=False)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)
    request_type: ModelApprovalRequestType = Field(
        default=ModelApprovalRequestType.CREATE,
        sa_column=Column(String(20), nullable=False, server_default=text("'create'")),
    )
    source_environment: str = Field(
        default=ModelEnvironment.TEST.value,
        sa_column=Column(String(20), nullable=False, server_default=text("'test'")),
    )
    target_environment: str = Field(
        default=ModelEnvironment.TEST.value,
        sa_column=Column(String(20), nullable=False, server_default=text("'test'")),
    )
    final_target_environment: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    visibility_requested: str = Field(
        default=ModelVisibilityScope.PRIVATE.value,
        sa_column=Column(String(20), nullable=False, server_default=text("'private'")),
    )
    requested_by: UUID = Field(foreign_key="user.id", nullable=False)
    request_to: UUID = Field(foreign_key="user.id", nullable=False)
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    reviewed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    decision: ApprovalDecisionEnum | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    justification: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    file_path: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )


class ModelApprovalRequest(ModelApprovalRequestBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "model_approval_request"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    __table_args__ = (
        Index("ix_model_approval_model_id", "model_id"),
        Index("ix_model_approval_org", "org_id"),
        Index("ix_model_approval_dept", "dept_id"),
        Index("ix_model_approval_request_to_decision", "request_to", "decision"),
        Index("ix_model_approval_requested_by_decision", "requested_by", "decision"),
    )


class ModelApprovalRequestCreate(SQLModel):
    model_id: UUID
    requested_by: UUID
    request_to: UUID
    request_type: ModelApprovalRequestType = ModelApprovalRequestType.CREATE
    source_environment: str = ModelEnvironment.TEST.value
    target_environment: str = ModelEnvironment.TEST.value
    final_target_environment: str | None = None
    visibility_requested: str = ModelVisibilityScope.PRIVATE.value
    org_id: UUID | None = None
    dept_id: UUID | None = None


class ModelApprovalRequestRead(BaseModel):
    id: UUID
    model_id: UUID
    org_id: UUID | None = None
    dept_id: UUID | None = None
    request_type: ModelApprovalRequestType
    source_environment: str
    target_environment: str
    final_target_environment: str | None = None
    visibility_requested: str
    requested_by: UUID
    request_to: UUID
    requested_at: datetime
    reviewed_at: datetime | None = None
    decision: ApprovalDecisionEnum | None = None
    justification: str | None = None
    file_path: dict | None = None
    created_at: datetime
    updated_at: datetime


class ModelApprovalRequestUpdate(BaseModel):
    reviewed_at: datetime | None = None
    decision: ApprovalDecisionEnum | None = None
    justification: str | None = None
    file_path: dict | None = None
    final_target_environment: str | None = None
