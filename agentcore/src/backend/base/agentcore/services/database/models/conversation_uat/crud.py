"""CRUD helpers for the conversation_uat table."""
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import col, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.services.database.models.conversation_uat.model import ConversationUATTable


async def add_conversation_uat(
    message: ConversationUATTable,
    session: AsyncSession,
) -> ConversationUATTable:
    """Insert a single UAT conversation record and return it."""
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def get_conversations_uat(
    session: AsyncSession,
    *,
    session_id: str | None = None,
    agent_id: UUID | None = None,
    deployment_id: UUID | None = None,
) -> list[ConversationUATTable]:
    """Return UAT conversations with optional filters, ordered by timestamp."""
    stmt = select(ConversationUATTable)
    if session_id:
        stmt = stmt.where(ConversationUATTable.session_id == session_id)
    if agent_id:
        stmt = stmt.where(ConversationUATTable.agent_id == agent_id)
    if deployment_id:
        stmt = stmt.where(ConversationUATTable.deployment_id == deployment_id)
    stmt = stmt.order_by(col(ConversationUATTable.timestamp).asc())
    results = await session.exec(stmt)
    return list(results.all())


async def delete_conversations_uat_by_deployment(
    session: AsyncSession,
    deployment_id: UUID,
) -> int:
    """Delete all UAT conversations for a deployment. Returns count of deleted rows."""
    stmt = delete(ConversationUATTable).where(ConversationUATTable.deployment_id == deployment_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount  # type: ignore[return-value]
