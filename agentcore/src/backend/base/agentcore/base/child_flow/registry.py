# TARGET PATH: src/backend/base/agentcore/base/child_flow/registry.py
"""Child Flow Registry for discovering and managing child flows.

This module provides a registry for discovering available agents that can be
called as child flows within a parent flow.
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
class FlowInfo:
    """Information about a flow available as a child flow."""

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


class ChildFlowRegistry:
    """Registry for discovering available child flows.

    This class provides methods for discovering agents/flows that can be called
    as child flows, with support for filtering and validation.
    """

    @classmethod
    async def list_available_flows(
        cls,
        user_id: str,
        exclude_flow_id: str | None = None,
        project_id: str | None = None,
    ) -> list[FlowInfo]:
        """List all agents available as child flows."""
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
                    if exclude_flow_id and agent_id_str == exclude_flow_id:
                        continue

                    result.append(
                        FlowInfo(
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
    async def get_flow_by_name(
        cls,
        flow_name: str,
        user_id: str,
    ) -> FlowInfo | None:
        """Get an agent by its name."""
        if not user_id:
            msg = "User ID is required"
            raise ValueError(msg)

        try:
            async with session_scope() as session:
                uuid_user_id = UUID(user_id) if isinstance(user_id, str) else user_id

                stmt = (
                    select(Agent)
                    .where(Agent.name == flow_name)
                    .where(Agent.user_id == uuid_user_id)
                )
                agent = (await session.exec(stmt)).first()

                if agent:
                    return FlowInfo(
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
    async def get_flow_by_id(
        cls,
        flow_id: str,
        user_id: str,
    ) -> FlowInfo | None:
        """Get an agent by its ID."""
        if not user_id:
            msg = "User ID is required"
            raise ValueError(msg)

        try:
            async with session_scope() as session:
                uuid_flow_id = UUID(flow_id) if isinstance(flow_id, str) else flow_id
                agent = await session.get(Agent, uuid_flow_id)

                if agent and str(agent.user_id) == user_id:
                    return FlowInfo(
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
    async def validate_child_flow_call(
        cls,
        parent_flow_id: str,
        child_flow_name: str,
        user_id: str,
    ) -> tuple[bool, str | None]:
        """Validate that a child flow call is allowed."""
        child_flow = await cls.get_flow_by_name(child_flow_name, user_id)

        if not child_flow:
            return False, f"Child flow '{child_flow_name}' not found"

        if child_flow.id == parent_flow_id:
            return False, "A flow cannot call itself as a child flow"

        return True, None

    @classmethod
    async def get_flow_names(cls, user_id: str, exclude_flow_id: str | None = None) -> list[str]:
        """Get list of agent names available as child flows."""
        flows = await cls.list_available_flows(user_id, exclude_flow_id)
        return [flow.name for flow in flows]
