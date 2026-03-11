from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import String, Text
from sqlmodel import Field, SQLModel, Column, JSON


class EvaluatorBase(SQLModel):
    name: str
    criteria: str = Field(sa_column=Column(Text, nullable=False))
    model: str | None = "gpt-4o"
    model_registry_id: Optional[str] = Field(default=None, index=True)
    preset_id: Optional[str] = None
    ground_truth: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    target: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    trace_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_ids: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    agent_id: Optional[str] = None  # Alias for agent_id (agents are agents)
    agent_ids: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))  # Alias for agent_ids
    agent_name: Optional[str] = None
    session_id: Optional[str] = None
    project_name: Optional[str] = None
    ts_from: Optional[datetime] = None
    ts_to: Optional[datetime] = None
    visibility: str = Field(
        default="private",
        sa_column=Column(String(20), nullable=False, default="private"),
    )
    public_scope: Optional[str] = Field(default=None, sa_column=Column(String(20), nullable=True))
    shared_user_ids: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    public_dept_ids: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))


class Evaluator(EvaluatorBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID | None = Field(default=None, index=True, nullable=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", index=True, nullable=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", index=True, nullable=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_response(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "criteria": self.criteria,
            "model": self.model,
            "model_registry_id": self.model_registry_id,
            "user_id": str(self.user_id) if self.user_id else None,
            "org_id": str(self.org_id) if self.org_id else None,
            "dept_id": str(self.dept_id) if self.dept_id else None,
            "preset_id": self.preset_id,
            "agent_ids": self.agent_ids,
            "agent_id": self.agent_id,
            "agent_ids": self.agent_ids,
            "target": self.target,
            "ground_truth": self.ground_truth,
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "session_id": self.session_id,
            "project_name": self.project_name,
            "ts_from": self.ts_from.isoformat() if self.ts_from else None,
            "ts_to": self.ts_to.isoformat() if self.ts_to else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "visibility": self.visibility or "private",
            "public_scope": self.public_scope,
            "shared_user_ids": self.shared_user_ids,
            "public_dept_ids": self.public_dept_ids,
        }
