# Path: src/backend/base/agentcore/services/teams/conversation_store.py
"""Redis-backed conversation store for mapping Teams conversations to agentcore sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from loguru import logger

from agentcore.schema.teams import TeamsConversationState


class ConversationStore:
    """Maps Teams conversation IDs to agentcore agent_id + session_id.

    Uses Redis with TTL-based expiry. Falls back to in-memory dict
    if Redis is unavailable.
    """

    PREFIX = "teams:conv:"
    TTL = 86400  # 24 hours

    def __init__(self, cache_service=None):
        self._cache = cache_service
        self._fallback: dict[str, TeamsConversationState] = {}

    async def set_mapping(
        self,
        conversation_id: str,
        agent_id: str,
        session_id: str | None = None,
        user_display_name: str | None = None,
        user_aad_object_id: str | None = None,
    ) -> TeamsConversationState:
        """Store a conversation-to-agent mapping."""
        if not session_id:
            session_id = str(uuid4())

        state = TeamsConversationState(
            agent_id=agent_id,
            session_id=session_id,
            user_display_name=user_display_name,
            user_aad_object_id=user_aad_object_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        key = f"{self.PREFIX}{conversation_id}"
        data = state.model_dump_json()

        try:
            if self._cache:
                await self._cache.set(key, data, expiration=self.TTL)
            else:
                self._fallback[conversation_id] = state
        except Exception:
            logger.warning(f"Failed to store Teams conversation mapping in Redis for {conversation_id}, using fallback")
            self._fallback[conversation_id] = state

        return state

    async def get_mapping(self, conversation_id: str) -> TeamsConversationState | None:
        """Retrieve a conversation mapping."""
        key = f"{self.PREFIX}{conversation_id}"

        try:
            if self._cache:
                data = await self._cache.get(key)
                if data:
                    return TeamsConversationState.model_validate_json(data)
        except Exception:
            logger.warning(f"Failed to get Teams conversation mapping from Redis for {conversation_id}")

        return self._fallback.get(conversation_id)

    async def delete_mapping(self, conversation_id: str) -> None:
        """Remove a conversation mapping."""
        key = f"{self.PREFIX}{conversation_id}"

        try:
            if self._cache:
                await self._cache.delete(key)
        except Exception:
            logger.warning(f"Failed to delete Teams conversation mapping from Redis for {conversation_id}")

        self._fallback.pop(conversation_id, None)

    async def update_session_id(self, conversation_id: str, session_id: str) -> TeamsConversationState | None:
        """Update the session_id for an existing conversation mapping."""
        state = await self.get_mapping(conversation_id)
        if not state:
            return None

        return await self.set_mapping(
            conversation_id=conversation_id,
            agent_id=state.agent_id,
            session_id=session_id,
            user_display_name=state.user_display_name,
            user_aad_object_id=state.user_aad_object_id,
        )
