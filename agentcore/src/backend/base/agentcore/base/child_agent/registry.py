# TARGET PATH: src/backend/base/agentcore/base/child_agent/registry.py
"""Child Agent Registry for discovering and managing child agents.

This module provides a registry for discovering available agents that can be
called as child agents within a parent agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from loguru import logger
from sqlmodel import select

from agentcore.services.database.models.agent.model import Agent
from agentcore.services.deps import session_scope

if TYPE_CHECKING:
    pass


@dataclass
class AgentInfo:
    """Information about an agent available as a child agent."""

    id: str
    name: str
    description: str | None
    project_id: str | None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "project_id": self.project_id,
        }


class ChildAgentRegistry:
    """Registry for discovering available child agents.

    This class provides methods for discovering agents that can be called
    as child agents, with support for filtering and validation.
    """

    @classmethod
    async def list_available_agents(
        cls,
        user_id: str,
        exclude_agent_id: str | None = None,
        project_id: str | None = None,
    ) -> list[AgentInfo]:
        """List all agents available as child agents."""
        if not user_id:
            msg = "User ID is required"
            raise ValueError(msg)

        try:
            async with session_scope() as session:
                uuid_user_id = UUID(user_id) if isinstance(user_id, str) else user_id

                stmt = select(Agent).where(Agent.user_id == uuid_user_id)

                if project_id:
                    uuid_project_id = UUID(project_id) if isinstance(project_id, str) else project_id
                    stmt = stmt.where(Agent.project_id == uuid_project_id)

                agents = (await session.exec(stmt)).all()

                result = []
                for agent in agents:
                    agent_id_str = str(agent.id)
                    if exclude_agent_id and agent_id_str == exclude_agent_id:
                        continue

                    result.append(
                        AgentInfo(
                            id=agent_id_str,
                            name=agent.name,
                            description=agent.description,
                            project_id=str(agent.project_id) if agent.project_id else None,
                            data=agent.data,
                        )
                    )

                return result

        except Exception as e:
            logger.exception(f"Error listing available agents: {e}")
            msg = f"Error listing agents: {e}"
            raise ValueError(msg) from e

    @classmethod
    async def get_agent_by_name(
        cls,
        agent_name: str,
        user_id: str,
    ) -> AgentInfo | None:
        """Get an agent by its name.

        First tries to find the agent owned by the given user.  If not found,
        falls back to a cross-user lookup so that published/orchestrated agents
        can call child agents owned by a different user (e.g. the agent creator).
        """
        if not user_id:
            msg = "User ID is required"
            raise ValueError(msg)

        try:
            async with session_scope() as session:
                uuid_user_id = UUID(user_id) if isinstance(user_id, str) else user_id

                # 1. Try exact match (same user)
                stmt = (
                    select(Agent)
                    .where(Agent.name == agent_name)
                    .where(Agent.user_id == uuid_user_id)
                )
                agent = (await session.exec(stmt)).first()

                # 2. Fallback: search across all users
                if not agent:
                    logger.info(
                        f"Child agent '{agent_name}' not found for user {user_id}, "
                        f"trying cross-user lookup"
                    )
                    stmt = select(Agent).where(Agent.name == agent_name)
                    agent = (await session.exec(stmt)).first()

                if agent:
                    return AgentInfo(
                        id=str(agent.id),
                        name=agent.name,
                        description=agent.description,
                        project_id=str(agent.project_id) if agent.project_id else None,
                        data=agent.data,
                    )

                return None

        except Exception as e:
            logger.exception(f"Error getting agent by name: {e}")
            return None

    @classmethod
    async def get_agent_by_id(
        cls,
        agent_id: str,
        user_id: str,
    ) -> AgentInfo | None:
        """Get an agent by its ID.

        Returns the agent if it exists.  The user_id check is relaxed so that
        orchestrated / published agents can invoke child agents owned by the
        agent creator (who may differ from the runtime user).
        """
        if not user_id:
            msg = "User ID is required"
            raise ValueError(msg)

        try:
            async with session_scope() as session:
                uuid_agent_id = UUID(agent_id) if isinstance(agent_id, str) else agent_id
                agent = await session.get(Agent, uuid_agent_id)

                if agent:
                    if str(agent.user_id) != user_id:
                        logger.info(
                            f"Child agent '{agent_id}' found via cross-user lookup "
                            f"(owner={agent.user_id}, caller={user_id})"
                        )
                    return AgentInfo(
                        id=str(agent.id),
                        name=agent.name,
                        description=agent.description,
                        project_id=str(agent.project_id) if agent.project_id else None,
                        data=agent.data,
                    )

                return None

        except Exception as e:
            logger.exception(f"Error getting agent by ID: {e}")
            return None

    @classmethod
    async def validate_child_agent_call(
        cls,
        parent_agent_id: str,
        child_agent_name: str,
        user_id: str,
    ) -> tuple[bool, str | None]:
        """Validate that a child agent call is allowed."""
        child_agent = await cls.get_agent_by_name(child_agent_name, user_id)

        if not child_agent:
            return False, f"Child agent '{child_agent_name}' not found"

        if child_agent.id == parent_agent_id:
            return False, "An agent cannot call itself as a child agent"

        return True, None

    @classmethod
    async def get_agent_names(cls, user_id: str, exclude_agent_id: str | None = None) -> list[str]:
        """Get list of agent names available as child agents."""
        agents = await cls.list_available_agents(user_id, exclude_agent_id)
        return [agent.name for agent in agents]
