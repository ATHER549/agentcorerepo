from datetime import datetime, timezone
from uuid import UUID

from loguru import logger
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.database.models.trigger_config.model import (
    TriggerConfigCreate,
    TriggerConfigTable,
    TriggerConfigUpdate,
    TriggerExecutionLogTable,
    TriggerExecutionStatusEnum,
    TriggerTypeEnum,
)


# ── TriggerConfig CRUD ─────────────────────────────────────────────────────


async def create_trigger_config(db: AsyncSession, data: TriggerConfigCreate) -> TriggerConfigTable:
    """Create a new trigger configuration."""
    record = TriggerConfigTable(**data.model_dump())
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_trigger_config_by_id(db: AsyncSession, trigger_id: UUID) -> TriggerConfigTable | None:
    """Get a trigger config by ID."""
    stmt = select(TriggerConfigTable).where(TriggerConfigTable.id == trigger_id)
    result = await db.exec(stmt)
    return result.first()


async def get_triggers_by_agent_id(
    db: AsyncSession,
    agent_id: UUID,
    *,
    active_only: bool = False,
) -> list[TriggerConfigTable]:
    """Get all trigger configs for an agent."""
    stmt = select(TriggerConfigTable).where(TriggerConfigTable.agent_id == agent_id)
    if active_only:
        stmt = stmt.where(TriggerConfigTable.is_active == True)  # noqa: E712
    stmt = stmt.order_by(col(TriggerConfigTable.created_at).desc())
    result = await db.exec(stmt)
    return list(result.all())


async def get_active_triggers_by_type(
    db: AsyncSession,
    trigger_type: TriggerTypeEnum,
) -> list[TriggerConfigTable]:
    """Get all active trigger configs of a specific type."""
    stmt = (
        select(TriggerConfigTable)
        .where(TriggerConfigTable.trigger_type == trigger_type)
        .where(TriggerConfigTable.is_active == True)  # noqa: E712
    )
    result = await db.exec(stmt)
    return list(result.all())


async def get_all_triggers(
    db: AsyncSession,
    *,
    trigger_type: TriggerTypeEnum | None = None,
) -> list[TriggerConfigTable]:
    """Get all trigger configs across all agents (admin view)."""
    stmt = select(TriggerConfigTable).order_by(col(TriggerConfigTable.created_at).desc())
    if trigger_type:
        stmt = stmt.where(TriggerConfigTable.trigger_type == trigger_type)
    result = await db.exec(stmt)
    return list(result.all())


async def get_all_active_triggers(db: AsyncSession) -> list[TriggerConfigTable]:
    """Get all active trigger configs across all agents."""
    stmt = (
        select(TriggerConfigTable)
        .where(TriggerConfigTable.is_active == True)  # noqa: E712
        .order_by(col(TriggerConfigTable.created_at))
    )
    result = await db.exec(stmt)
    return list(result.all())


async def update_trigger_config(
    db: AsyncSession,
    trigger_id: UUID,
    data: TriggerConfigUpdate,
) -> TriggerConfigTable | None:
    """Update a trigger configuration."""
    record = await get_trigger_config_by_id(db, trigger_id)
    if not record:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(record, key, value)
    record.updated_at = datetime.now(timezone.utc)

    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def toggle_trigger(db: AsyncSession, trigger_id: UUID) -> TriggerConfigTable | None:
    """Toggle a trigger's active status."""
    record = await get_trigger_config_by_id(db, trigger_id)
    if not record:
        return None

    record.is_active = not record.is_active
    record.updated_at = datetime.now(timezone.utc)

    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def delete_trigger_config(db: AsyncSession, trigger_id: UUID) -> bool:
    """Delete a trigger configuration and its execution logs."""
    record = await get_trigger_config_by_id(db, trigger_id)
    if not record:
        return False

    # Delete child execution logs first to satisfy FK constraint
    logs_stmt = select(TriggerExecutionLogTable).where(
        TriggerExecutionLogTable.trigger_config_id == trigger_id
    )
    logs_result = await db.exec(logs_stmt)
    for log in logs_result.all():
        await db.delete(log)

    await db.delete(record)
    await db.commit()
    return True


async def update_trigger_last_run(db: AsyncSession, trigger_id: UUID) -> None:
    """Update the last triggered timestamp and increment trigger count."""
    record = await get_trigger_config_by_id(db, trigger_id)
    if record:
        record.last_triggered_at = datetime.now(timezone.utc)
        record.trigger_count += 1
        record.updated_at = datetime.now(timezone.utc)
        db.add(record)
        await db.commit()


async def deactivate_triggers_for_agent(
    db: AsyncSession,
    agent_id: UUID,
    environment: str,
) -> int:
    """Deactivate all triggers for an agent in a specific environment."""
    stmt = (
        select(TriggerConfigTable)
        .where(TriggerConfigTable.agent_id == agent_id)
        .where(TriggerConfigTable.environment == environment)
        .where(TriggerConfigTable.is_active == True)  # noqa: E712
    )
    result = await db.exec(stmt)
    records = list(result.all())
    count = 0
    for record in records:
        record.is_active = False
        record.updated_at = datetime.now(timezone.utc)
        db.add(record)
        count += 1

    if count > 0:
        await db.commit()
    return count


# ── TriggerExecutionLog CRUD ──────────────────────────────────────────────


async def log_trigger_execution(
    db: AsyncSession,
    trigger_config_id: UUID,
    agent_id: UUID,
    status: TriggerExecutionStatusEnum,
    *,
    error_message: str | None = None,
    execution_duration_ms: int | None = None,
    payload: dict | None = None,
) -> TriggerExecutionLogTable:
    """Log a trigger execution event."""
    log_entry = TriggerExecutionLogTable(
        trigger_config_id=trigger_config_id,
        agent_id=agent_id,
        status=status,
        error_message=error_message,
        execution_duration_ms=execution_duration_ms,
        payload=payload,
    )
    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)
    return log_entry


async def get_trigger_execution_logs(
    db: AsyncSession,
    trigger_config_id: UUID,
    *,
    limit: int = 50,
) -> list[TriggerExecutionLogTable]:
    """Get execution logs for a trigger config."""
    stmt = (
        select(TriggerExecutionLogTable)
        .where(TriggerExecutionLogTable.trigger_config_id == trigger_config_id)
        .order_by(col(TriggerExecutionLogTable.triggered_at).desc())
        .limit(limit)
    )
    result = await db.exec(stmt)
    return list(result.all())