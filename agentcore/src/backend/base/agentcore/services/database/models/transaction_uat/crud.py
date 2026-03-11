"""CRUD helpers for the transaction_uat table."""
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import col, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.services.database.models.transaction_uat.model import TransactionUATTable


async def log_transaction_uat(
    transaction: TransactionUATTable,
    session: AsyncSession,
) -> TransactionUATTable:
    """Insert a single UAT transaction record."""
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)
    return transaction


async def get_transactions_uat(
    session: AsyncSession,
    *,
    agent_id: UUID | None = None,
    deployment_id: UUID | None = None,
) -> list[TransactionUATTable]:
    """Return UAT transactions with optional filters."""
    stmt = select(TransactionUATTable)
    if agent_id:
        stmt = stmt.where(TransactionUATTable.agent_id == agent_id)
    if deployment_id:
        stmt = stmt.where(TransactionUATTable.deployment_id == deployment_id)
    stmt = stmt.order_by(col(TransactionUATTable.timestamp).asc())
    results = await session.exec(stmt)
    return list(results.all())


async def delete_transactions_uat_by_deployment(
    session: AsyncSession,
    deployment_id: UUID,
) -> int:
    """Delete all UAT transactions for a deployment. Returns count of deleted rows."""
    stmt = delete(TransactionUATTable).where(TransactionUATTable.deployment_id == deployment_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount  # type: ignore[return-value]
