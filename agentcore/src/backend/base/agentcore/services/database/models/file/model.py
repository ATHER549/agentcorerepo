from datetime import datetime, timezone
from uuid import UUID, uuid4
from agentcore.schema.serialize import UUIDstr
from sqlmodel import Field, SQLModel

class File(SQLModel, table=True):  # type: ignore[call-arg]
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id")
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    knowledge_base_id: UUID | None = Field(default=None, foreign_key="knowledge_base.id", nullable=True, index=True)
    name: str = Field(unique=True, nullable=False)
    path: str = Field(nullable=False)
    size: int = Field(nullable=False)
    provider: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
