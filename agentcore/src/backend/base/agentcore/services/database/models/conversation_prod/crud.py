"""CRUD helpers for the conversation_prod table."""
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import col, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.services.database.models.conversation_prod.model import ConversationProdTable


async def add_conversation_prod(
    message: ConversationProdTable,
    session: AsyncSession,
) -> ConversationProdTable:
    """Insert a single prod conversation record and return it."""
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def get_conversations_prod(
    session: AsyncSession,
    *,
    session_id: str | None = None,
    agent_id: UUID | None = None,
    deployment_id: UUID | None = None,
) -> list[ConversationProdTable]:
    """Return prod conversations with optional filters, ordered by timestamp."""
    stmt = select(ConversationProdTable)
    if session_id:
        stmt = stmt.where(ConversationProdTable.session_id == session_id)
    if agent_id:
        stmt = stmt.where(ConversationProdTable.agent_id == agent_id)
    if deployment_id:
        stmt = stmt.where(ConversationProdTable.deployment_id == deployment_id)
    stmt = stmt.order_by(col(ConversationProdTable.timestamp).asc())
    results = await session.exec(stmt)
    return list(results.all())


async def delete_conversations_prod_by_deployment(
    session: AsyncSession,
    deployment_id: UUID,
) -> int:
    """Delete all prod conversations for a deployment. Returns count of deleted rows."""
    stmt = delete(ConversationProdTable).where(ConversationProdTable.deployment_id == deployment_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount  # type: ignore[return-value]
