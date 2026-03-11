"""CRUD helpers for the orch_transaction table."""
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import col, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.services.database.models.orch_transaction.model import OrchTransactionTable


async def orch_log_transaction(
    transaction: OrchTransactionTable,
    session: AsyncSession,
) -> OrchTransactionTable:
    """Insert a single transaction record."""
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)
    return transaction


async def orch_get_transactions(
    session: AsyncSession,
    *,
    session_id: str | None = None,
    agent_id: UUID | None = None,
) -> list[OrchTransactionTable]:
    """Return transactions with optional filters."""
    stmt = select(OrchTransactionTable)
    if session_id:
        stmt = stmt.where(OrchTransactionTable.session_id == session_id)
    if agent_id:
        stmt = stmt.where(OrchTransactionTable.agent_id == agent_id)
    stmt = stmt.order_by(col(OrchTransactionTable.timestamp).asc())
    results = await session.exec(stmt)
    return list(results.all())


async def orch_delete_session_transactions(
    session: AsyncSession,
    session_id: str,
) -> int:
    """Delete all transactions for a session. Returns count of deleted rows."""
    stmt = delete(OrchTransactionTable).where(OrchTransactionTable.session_id == session_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount  # type: ignore[return-value]
