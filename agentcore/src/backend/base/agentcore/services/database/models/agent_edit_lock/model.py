from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class AgentEditLock(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "agent_edit_lock"

    agent_id: UUID = Field(primary_key=True, foreign_key="agent.id", nullable=False)
    locked_by: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    locked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

