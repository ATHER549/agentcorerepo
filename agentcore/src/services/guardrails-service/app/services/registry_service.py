"""CRUD operations for the guardrail_catalogue table."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardrail_catalogue import (
    GuardrailCatalogue,
    GuardrailCatalogueCreate,
    GuardrailCatalogueRead,
    GuardrailCatalogueUpdate,
)

logger = logging.getLogger(__name__)


async def create_guardrail(
    session: AsyncSession,
    data: GuardrailCatalogueCreate,
) -> GuardrailCatalogueRead:
    """Insert a new guardrail into the catalogue."""
    now = datetime.now(timezone.utc)
    row = GuardrailCatalogue(
        name=data.name,
        description=data.description,
        framework=data.framework,
        provider=data.provider,
        model_registry_id=data.model_registry_id,
        category=data.category,
        status=data.status,
        rules_count=data.rules_count,
        is_custom=data.is_custom,
        runtime_config=data.runtime_config,
        org_id=data.org_id,
        dept_id=data.dept_id,
        visibility=data.visibility,
        public_scope=data.public_scope,
        public_dept_ids=data.public_dept_ids,
        shared_user_ids=data.shared_user_ids,
        created_by=data.created_by,
        updated_by=data.updated_by,
        created_at=now,
        updated_at=now,
        published_by=data.published_by,
        published_at=data.published_at,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return GuardrailCatalogueRead.from_orm_model(row)


async def get_guardrails(
    session: AsyncSession,
    *,
    framework: str | None = None,
    status: str | None = None,
    active_only: bool = False,
) -> list[GuardrailCatalogueRead]:
    """Return all guardrail catalogue entries, optionally filtered."""
    stmt = select(GuardrailCatalogue).order_by(GuardrailCatalogue.name)
    if active_only or status == "active":
        stmt = stmt.where(GuardrailCatalogue.status == "active")
    elif status:
        stmt = stmt.where(GuardrailCatalogue.status == status)
    if framework:
        stmt = stmt.where(GuardrailCatalogue.framework == framework)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [GuardrailCatalogueRead.from_orm_model(r) for r in rows]


async def get_guardrail(session: AsyncSession, guardrail_id: UUID) -> GuardrailCatalogueRead | None:
    """Return a single guardrail by ID."""
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        return None
    return GuardrailCatalogueRead.from_orm_model(row)


async def update_guardrail(
    session: AsyncSession,
    guardrail_id: UUID,
    data: GuardrailCatalogueUpdate,
) -> GuardrailCatalogueRead | None:
    """Update an existing guardrail entry."""
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        return None

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(row, field, value)

    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return GuardrailCatalogueRead.from_orm_model(row)


async def delete_guardrail(session: AsyncSession, guardrail_id: UUID) -> bool:
    """Hard-delete a guardrail entry. Returns True if the row existed."""
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def get_active_nemo_guardrails(session: AsyncSession) -> list[GuardrailCatalogueRead]:
    """Return all active NeMo guardrails that have a model_registry_id set."""
    stmt = (
        select(GuardrailCatalogue)
        .where(
            GuardrailCatalogue.framework == "nemo",
            GuardrailCatalogue.status == "active",
            GuardrailCatalogue.model_registry_id.is_not(None),
        )
        .order_by(GuardrailCatalogue.name.asc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [GuardrailCatalogueRead.from_orm_model(r) for r in rows]
