# Path: src/backend/agentcore/services/database/models/orch_transaction/model.py
#
# Dedicated transaction table for Orchestrator Chat.
# Logs node execution details for orchestrator sessions against UAT/PROD deployments.

from datetime import datetime, timezone

from uuid import UUID, uuid4

from pydantic import field_serializer, field_validator
from sqlalchemy import ForeignKey as SAForeignKey, Index, Uuid as SAUuid
from sqlmodel import JSON, Column, Field, SQLModel

from agentcore.serialization.serialization import get_max_items_length, get_max_text_length, serialize


class OrchTransactionBase(SQLModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    vertex_id: str = Field(nullable=False)
    target_id: str | None = Field(default=None)
    inputs: dict | None = Field(default=None, sa_column=Column(JSON))
    outputs: dict | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(nullable=False)
    error: str | None = Field(default=None)
    agent_id: UUID = Field()
    session_id: str | None = Field(default=None)

    class Config:
        arbitrary_types_allowed = True

    @field_validator("agent_id", mode="before")
    @classmethod
    def validate_agent_id(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = UUID(value)
        return value

    @field_serializer("inputs")
    def serialize_inputs(self, data) -> dict:
        return serialize(data, max_length=get_max_text_length(), max_items=get_max_items_length())

    @field_serializer("outputs")
    def serialize_outputs(self, data) -> dict:
        return serialize(data, max_length=get_max_text_length(), max_items=get_max_items_length())


class OrchTransactionTable(OrchTransactionBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "orch_transaction"
    id: UUID | None = Field(default_factory=uuid4, primary_key=True)

    org_id: UUID | None = Field(
        default=None,
        sa_column=Column(SAUuid(), SAForeignKey("organization.id", ondelete="SET NULL"), nullable=True),
    )
    dept_id: UUID | None = Field(
        default=None,
        sa_column=Column(SAUuid(), SAForeignKey("department.id", ondelete="SET NULL"), nullable=True),
    )
    deployment_id: UUID | None = Field(
        default=None,
        sa_column=Column(SAUuid(), nullable=True),
    )

    __table_args__ = (
        Index("ix_orch_transaction_agent", "agent_id"),
        Index("ix_orch_transaction_session", "session_id"),
        Index("ix_orch_transaction_org", "org_id"),
        Index("ix_orch_transaction_dept", "dept_id"),
        Index("ix_orch_transaction_deployment", "deployment_id"),
    )


class OrchTransactionReadResponse(OrchTransactionBase):
    id: UUID = Field(alias="transaction_id")
    agent_id: UUID
    org_id: UUID | None = None
    dept_id: UUID | None = None
    deployment_id: UUID | None = None
