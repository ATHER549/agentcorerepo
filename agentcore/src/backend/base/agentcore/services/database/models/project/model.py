from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlmodel import JSON, Column, Field, Relationship, SQLModel

from agentcore.services.database.models.agent.model import Agent, AgentRead
from agentcore.services.database.models.user.model import User


class ProjectBase(SQLModel):
    name: str = Field(index=True)
    description: str | None = Field(default=None, sa_column=Column(Text))
    auth_settings: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Authentication settings for the folder/project",
    )


class Project(ProjectBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "project"

    id: UUID | None = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID | None = Field(default=None, foreign_key="organization.id", nullable=True, index=True)
    dept_id: UUID | None = Field(default=None, foreign_key="department.id", nullable=True, index=True)
    owner_user_id: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    status: str = Field(default="active", sa_column=Column(String(50), nullable=False))
    created_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    deleted_by: UUID | None = Field(default=None, foreign_key="user.id", nullable=True)

    user_id: UUID | None = Field(default=None, foreign_key="user.id")
    user: User = Relationship(
        back_populates="folders",
        sa_relationship_kwargs={"foreign_keys": "Project.user_id"},
    )
    agents: list[Agent] = Relationship(
        back_populates="folder", sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"}
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="unique_project_name"),
        ForeignKeyConstraint(
            ["org_id", "dept_id"],
            ["department.org_id", "department.id"],
            name="fk_project_org_id_dept_id_department",
        ),
    )


class ProjectCreate(ProjectBase):
    components_list: list[UUID] | None = None
    agents_list: list[UUID] | None = None


class ProjectRead(ProjectBase):
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_own_project: bool = False
    created_by_email: str | None = None
    department_name: str | None = None
    organization_name: str | None = None


class ProjectReadWithAgents(ProjectBase):
    id: UUID
    agents: list[AgentRead] = Field(default=[])

    def model_dump(self, **kwargs) -> dict:
        d = super().model_dump(**kwargs)
        if "agents" in d:
            d["agents"] = d.pop("agents")
        return d


class ProjectUpdate(SQLModel):
    name: str | None = None
    description: str | None = None
    components: list[UUID] = Field(default_factory=list)
    agents: list[UUID] = Field(default_factory=list)
    auth_settings: dict | None = None


# Backward-compatible aliases for existing imports.
FolderBase = ProjectBase
Folder = Project
FolderCreate = ProjectCreate
FolderRead = ProjectRead
FolderReadWithAgents = ProjectReadWithAgents
FolderUpdate = ProjectUpdate
