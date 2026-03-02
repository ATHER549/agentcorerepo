# Path: src/backend/agentcore/services/database/models/transaction_prod/model.py
#
# Clone of the dev TransactionTable for PROD environment.
# Adds deployment_id FK to link transactions to a specific PROD deployment version.

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from pydantic import field_serializer, field_validator
from sqlalchemy import Index
from sqlmodel import JSON, Column, Field, Relationship, SQLModel

from agentcore.serialization.serialization import get_max_items_length, get_max_text_length, serialize

if TYPE_CHECKING:
    from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd


class TransactionProdBase(SQLModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    vertex_id: str = Field(nullable=False)
    target_id: str | None = Field(default=None)
    inputs: dict | None = Field(default=None, sa_column=Column(JSON))
    outputs: dict | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(nullable=False)
    error: str | None = Field(default=None)
    agent_id: UUID = Field()
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True)

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


class TransactionProdTable(TransactionProdBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "transaction_prod"
    id: UUID | None = Field(default_factory=uuid4, primary_key=True)

    deployment_id: UUID | None = Field(
        default=None,
        foreign_key="agent_deployment_prod.id",
        index=True,
        description="Link to the specific PROD deployment version",
    )

    # Relationships
    deployment: Optional["AgentDeploymentProd"] = Relationship()

    __table_args__ = (
        Index("ix_transaction_prod_agent", "agent_id"),
        Index("ix_transaction_prod_org", "org_id"),
        Index("ix_transaction_prod_dept", "dept_id"),
        Index("ix_transaction_prod_deployment", "deployment_id"),
    )


class TransactionProdReadResponse(TransactionProdBase):
    id: UUID = Field(alias="transaction_id")
    agent_id: UUID
    deployment_id: UUID | None = None
