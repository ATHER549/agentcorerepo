"""CRUD helpers for the orch_conversation table."""
from uuid import UUID

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.services.database.models.orch_conversation.model import OrchConversationTable


async def orch_add_message(
    message: OrchConversationTable,
    session: AsyncSession,
) -> OrchConversationTable:
    """Insert a single message and return it with its generated id."""
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def orch_get_messages(
    session: AsyncSession,
    *,
    session_id: str | None = None,
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
    order_by: str = "timestamp",
) -> list[OrchConversationTable]:
    """Return messages with optional filters, ordered by timestamp."""
    stmt = select(OrchConversationTable)
    if session_id:
        stmt = stmt.where(OrchConversationTable.session_id == session_id)
    if agent_id:
        stmt = stmt.where(OrchConversationTable.agent_id == agent_id)
    if user_id:
        stmt = stmt.where(OrchConversationTable.user_id == user_id)
    if order_by == "timestamp":
        stmt = stmt.order_by(col(OrchConversationTable.timestamp).asc())
    results = await session.exec(stmt)
    return list(results.all())


async def orch_get_sessions(
    session: AsyncSession,
    user_id: UUID,
) -> list[dict]:
    """Return distinct session_ids for a user with the latest timestamp and first message preview."""
    from sqlalchemy import func, case

    stmt = (
        select(
            OrchConversationTable.session_id,
            func.max(OrchConversationTable.timestamp).label("last_timestamp"),
            func.min(
                case(
                    (OrchConversationTable.sender == "user", OrchConversationTable.text),
                    else_=None,
                )
            ).label("first_user_message"),
        )
        .where(OrchConversationTable.user_id == user_id)
        .group_by(OrchConversationTable.session_id)
        .order_by(func.max(OrchConversationTable.timestamp).desc())
    )
    results = await session.exec(stmt)
    rows = results.all()
    return [
        {
            "session_id": row.session_id,
            "last_timestamp": row.last_timestamp.isoformat() if row.last_timestamp else None,
            "preview": (row.first_user_message or "")[:80],
        }
        for row in rows
    ]


async def orch_delete_session(
    session: AsyncSession,
    session_id: str,
    user_id: UUID | None = None,
) -> int:
    """Delete all messages in a session. Returns count of deleted rows.

    When *user_id* is provided the delete is scoped to that user so that
    one user cannot delete another user's session.
    """
    stmt = delete(OrchConversationTable).where(OrchConversationTable.session_id == session_id)
    if user_id:
        stmt = stmt.where(OrchConversationTable.user_id == user_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount  # type: ignore[return-value]


async def orch_rename_session(
    session: AsyncSession,
    old_session_id: str,
    new_session_id: str,
    user_id: UUID | None = None,
) -> int:
    """Rename a session (update session_id on all its messages). Returns count of updated rows.

    When *user_id* is provided the update is scoped to that user so that
    one user cannot rename another user's session.
    """
    stmt = (
        update(OrchConversationTable)
        .where(OrchConversationTable.session_id == old_session_id)
    )
    if user_id:
        stmt = stmt.where(OrchConversationTable.user_id == user_id)
    stmt = stmt.values(session_id=new_session_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount  # type: ignore[return-value]


async def orch_get_active_agent(
    session: AsyncSession,
    session_id: str,
) -> dict | None:
    """Return agent_id and deployment_id from the most recent non-system message in the session.

    Used for sticky routing — when the user sends a message without @-mentioning
    an agent, the orchestrator routes to the last active agent.
    """
    stmt = (
        select(
            OrchConversationTable.agent_id,
            OrchConversationTable.deployment_id,
        )
        .where(OrchConversationTable.session_id == session_id)
        .where(OrchConversationTable.agent_id.isnot(None))
        .where(OrchConversationTable.category == "message")
        .order_by(col(OrchConversationTable.timestamp).desc())
        .limit(1)
    )
    result = await session.exec(stmt)
    row = result.first()
    if row:
        return {"agent_id": row.agent_id, "deployment_id": row.deployment_id}
    return None
