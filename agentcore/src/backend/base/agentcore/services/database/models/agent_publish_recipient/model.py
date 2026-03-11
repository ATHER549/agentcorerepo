from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Index, String, UniqueConstraint, text
from sqlmodel import Field, SQLModel


class AgentPublishRecipient(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "agent_publish_recipient"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agent.id", nullable=False, index=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID = Field(foreign_key="department.id", nullable=False, index=True)
    recipient_user_id: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    recipient_email: str = Field(
        sa_column=Column(String(320), nullable=False),
        description="Normalized recipient email in lowercase",
    )
    created_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text("now()")),
    )

    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "dept_id",
            "recipient_email",
            name="uq_agent_publish_recipient_agent_dept_email",
        ),
        Index("ix_agent_publish_recipient_dept_email", "dept_id", "recipient_email"),
    )


class AgentPublishRecipientRead(BaseModel):
    id: UUID
    agent_id: UUID
    org_id: UUID | None = None
    dept_id: UUID
    recipient_user_id: UUID
    recipient_email: str
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
