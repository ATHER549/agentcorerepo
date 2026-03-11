from fastapi_pagination import Page
from pydantic import Field

from agentcore.helpers.base_model import BaseModel
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.project.model import ProjectRead


class ProjectWithPaginatedAgents(BaseModel):
    model_config = {"populate_by_name": True}

    project: ProjectRead
    agents: Page[Agent] = Field(serialization_alias="agents")


# Backward-compatible alias.
FolderWithPaginatedAgents = ProjectWithPaginatedAgents
