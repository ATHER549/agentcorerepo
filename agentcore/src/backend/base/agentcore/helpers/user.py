from uuid import UUID

from fastapi import HTTPException
from sqlmodel import select

from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.user.model import User, UserRead
from agentcore.services.deps import get_db_service


async def get_user_by_agent_id_or_endpoint_name(agent_id_or_name: str) -> UserRead | None:
    async with get_db_service().with_session() as session:
        try:
            agent_id = UUID(agent_id_or_name)
            agent = await session.get(Agent, agent_id)
        except ValueError:
            stmt = select(Agent).where(Agent.name == agent_id_or_name)
            agent = (await session.exec(stmt)).first()

        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent identifier {agent_id_or_name} not found")

        user = await session.get(User, agent.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"User for agent {agent_id_or_name} not found")

        return UserRead.model_validate(user, from_attributes=True)
