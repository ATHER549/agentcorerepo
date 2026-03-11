# Path: src/backend/base/agentcore/schema/teams.py
"""Pydantic schemas for Microsoft Teams integration."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# --- Publish Request/Response ---


class TeamsPublishRequest(BaseModel):
    """Request to publish an agent as a Teams app."""

    agent_id: UUID
    display_name: str | None = None  # defaults to agent.name
    short_description: str | None = None  # defaults to agent.description
    long_description: str | None = None
    bot_app_id: str | None = None  # per-agent bot app ID (falls back to global)
    bot_app_secret: str | None = None  # per-agent bot secret (falls back to global)


class TeamsPublishResponse(BaseModel):
    """Response after initiating Teams publish."""

    teams_app_id: UUID  # internal DB ID
    agent_id: UUID
    status: str
    teams_external_id: str | None = None
    message: str


class TeamsUnpublishRequest(BaseModel):
    """Request to unpublish an agent from Teams."""

    agent_id: UUID


class TeamsAppStatusResponse(BaseModel):
    """Status of a Teams app publication."""

    agent_id: UUID
    status: str
    teams_external_id: str | None = None
    display_name: str
    published_at: datetime | None = None
    last_error: str | None = None
    has_own_bot: bool = False
    bot_app_id: str | None = None


# --- Conversation State ---


class TeamsConversationState(BaseModel):
    """Stored in Redis for mapping Teams conversations to agentcore sessions."""

    agent_id: str
    session_id: str
    user_display_name: str | None = None
    user_aad_object_id: str | None = None
    created_at: str  # ISO format


# --- Bot Framework Activity (simplified for type safety) ---


class TeamsActivityMessage(BaseModel):
    """Simplified representation of a Bot Framework Activity."""

    type: str = Field(description="Activity type: message, conversationUpdate, etc.")
    text: str | None = None
    conversation_id: str
    from_id: str
    from_name: str | None = None
    service_url: str
    channel_data: dict | None = None
