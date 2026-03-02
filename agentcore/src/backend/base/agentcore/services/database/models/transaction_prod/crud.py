"""CRUD helpers for the transaction_prod table."""
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import col, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.services.database.models.transaction_prod.model import TransactionProdTable


async def log_transaction_prod(
    transaction: TransactionProdTable,
    session: AsyncSession,
) -> TransactionProdTable:
    """Insert a single prod transaction record."""
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)
    return transaction


async def get_transactions_prod(
    session: AsyncSession,
    *,
    agent_id: UUID | None = None,
    deployment_id: UUID | None = None,
) -> list[TransactionProdTable]:
    """Return prod transactions with optional filters."""
    stmt = select(TransactionProdTable)
    if agent_id:
        stmt = stmt.where(TransactionProdTable.agent_id == agent_id)
    if deployment_id:
        stmt = stmt.where(TransactionProdTable.deployment_id == deployment_id)
    stmt = stmt.order_by(col(TransactionProdTable.timestamp).asc())
    results = await session.exec(stmt)
    return list(results.all())


async def delete_transactions_prod_by_deployment(
    session: AsyncSession,
    deployment_id: UUID,
) -> int:
    """Delete all prod transactions for a deployment. Returns count of deleted rows."""
    stmt = delete(TransactionProdTable).where(TransactionProdTable.deployment_id == deployment_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount  # type: ignore[return-value]
