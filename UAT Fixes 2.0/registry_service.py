"""CRUD operations for the guardrail_catalogue table."""

from __future__ import annotations

import hashlib
import json
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runtime_config_hash(config: dict | None) -> str:
    """Deterministic hash of a guardrail's runtime_config for sync comparison."""
    if not config:
        return ""
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


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
        environment="uat",  # New guardrails are always UAT
        latest_version=1
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
    """Update an existing guardrail entry.

    Production guardrails are immutable — updates are rejected.
    """
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        return None

    if row.environment == "prod":
        msg = "Production guardrails are immutable and cannot be edited."
        raise ValueError(msg)

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(row, field, value)

    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return GuardrailCatalogueRead.from_orm_model(row)


async def delete_guardrail(session: AsyncSession, guardrail_id: UUID) -> bool:
    """Hard-delete a guardrail entry. Returns True if the row existed.

    Production guardrails cannot be deleted.
    UAT guardrails with active production references cannot be deleted.
    """
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        return False

    if row.environment == "prod":
        msg = "Production guardrails cannot be deleted."
        raise ValueError(msg)

    if row.prod_ref_count > 0:
        msg = (
            f"Cannot delete guardrail '{row.name}' — it is referenced by "
            f"{row.prod_ref_count} active production deployment(s). "
            "Deprecate or remove the production agents first."
        )
        raise ValueError(msg)

    # Also delete the prod copy if it exists and has no references
    prod_copy = await _get_prod_copy(session, guardrail_id)
    if prod_copy is not None:
        await session.delete(prod_copy)

    await session.delete(row)
    await session.commit()
    return True


async def get_active_nemo_guardrails(session: AsyncSession) -> list[GuardrailCatalogueRead]:
    """Return all active UAT NeMo guardrails that have a model_registry_id set.

    Only UAT guardrails are returned — prod copies are auto-created during
    promotion and should not appear in the component dropdown.
    """
    stmt = (
        select(GuardrailCatalogue)
        .where(
            GuardrailCatalogue.framework == "nemo",
            GuardrailCatalogue.status == "active",
            GuardrailCatalogue.model_registry_id.is_not(None),
            GuardrailCatalogue.environment == "uat",
        )
        .order_by(GuardrailCatalogue.name.asc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [GuardrailCatalogueRead.from_orm_model(r) for r in rows]


# ---------------------------------------------------------------------------
# Promotion (UAT → PROD)
# ---------------------------------------------------------------------------


async def _get_prod_copy(session: AsyncSession, uat_guardrail_id: UUID) -> GuardrailCatalogue | None:
    """Find the prod copy of a UAT guardrail, if it exists."""
    stmt = select(GuardrailCatalogue).where(
        GuardrailCatalogue.source_guardrail_id == uat_guardrail_id,
        GuardrailCatalogue.environment == "prod",
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def promote_guardrail(
    session: AsyncSession,
    guardrail_id: UUID,
    promoted_by: UUID,
) -> tuple[GuardrailCatalogueRead, bool]:
    """Promote a UAT guardrail to production.

    Creates a frozen prod copy (or updates an existing one if the config has
    changed). Increments ``prod_ref_count`` on the UAT record.

    Returns ``(prod_guardrail_read, in_sync)`` where *in_sync* indicates
    whether the prod copy was already up-to-date.
    """
    uat_row = await session.get(GuardrailCatalogue, guardrail_id)
    if uat_row is None:
        msg = f"Guardrail {guardrail_id} not found."
        raise ValueError(msg)
    if uat_row.environment != "uat":
        msg = f"Guardrail {guardrail_id} is not a UAT guardrail — cannot promote."
        raise ValueError(msg)

    now = datetime.now(timezone.utc)
    prod_row = await _get_prod_copy(session, guardrail_id)

    if prod_row is None:
        # First promotion — deep-copy UAT → new PROD record
        prod_row = GuardrailCatalogue(
            name=uat_row.name,
            description=uat_row.description,
            framework=uat_row.framework,
            provider=uat_row.provider,
            model_registry_id=uat_row.model_registry_id,
            category=uat_row.category,
            status=uat_row.status,
            rules_count=uat_row.rules_count,
            is_custom=uat_row.is_custom,
            runtime_config=uat_row.runtime_config,
            org_id=uat_row.org_id,
            dept_id=uat_row.dept_id,
            visibility=uat_row.visibility,
            public_scope=uat_row.public_scope,
            public_dept_ids=uat_row.public_dept_ids,
            shared_user_ids=uat_row.shared_user_ids,
            created_by=uat_row.created_by,
            created_at=now,
            updated_by=promoted_by,
            updated_at=now,
            published_by=uat_row.published_by,
            published_at=uat_row.published_at,
            environment="prod",
            source_guardrail_id=guardrail_id,
            promoted_at=now,
            promoted_by=promoted_by,
        )
        session.add(prod_row)
        in_sync = True
        logger.info(
            "Guardrail promoted to prod (new copy): uat_id=%s, prod_id=%s",
            guardrail_id, prod_row.id,
        )
    else:
        # Prod copy exists — check if config has drifted
        uat_hash = _runtime_config_hash(uat_row.runtime_config)
        prod_hash = _runtime_config_hash(prod_row.runtime_config)
        in_sync = uat_hash == prod_hash

        if not in_sync:
            # Re-promote: update prod copy with current UAT config
            prod_row.name = uat_row.name
            prod_row.description = uat_row.description
            prod_row.framework = uat_row.framework
            prod_row.provider = uat_row.provider
            prod_row.model_registry_id = uat_row.model_registry_id
            prod_row.category = uat_row.category
            prod_row.status = uat_row.status
            prod_row.rules_count = uat_row.rules_count
            prod_row.is_custom = uat_row.is_custom
            prod_row.runtime_config = uat_row.runtime_config
            prod_row.promoted_at = now
            prod_row.promoted_by = promoted_by
            prod_row.updated_at = now
            in_sync = True
            logger.info(
                "Guardrail re-promoted to prod (config updated): uat_id=%s, prod_id=%s",
                guardrail_id, prod_row.id,
            )
        else:
            logger.info(
                "Guardrail promotion idempotent (already in sync): uat_id=%s, prod_id=%s",
                guardrail_id, prod_row.id,
            )

    # Increment prod ref count on UAT record
    uat_row.prod_ref_count = (uat_row.prod_ref_count or 0) + 1
    session.add(uat_row)

    await session.commit()
    await session.refresh(prod_row)
    await session.refresh(uat_row)
    return GuardrailCatalogueRead.from_orm_model(prod_row), in_sync


async def demote_guardrail(
    session: AsyncSession,
    guardrail_id: UUID,
) -> tuple[int, UUID | None]:
    """Decrement prod_ref_count on a UAT guardrail when a prod deployment is removed.

    Returns ``(new_ref_count, source_guardrail_id)``.
    The *guardrail_id* can be either the UAT ID or the prod copy ID.
    """
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        msg = f"Guardrail {guardrail_id} not found."
        raise ValueError(msg)

    # Resolve to the UAT record
    if row.environment == "prod":
        uat_id = row.source_guardrail_id
        if uat_id is None:
            msg = f"Prod guardrail {guardrail_id} has no source_guardrail_id."
            raise ValueError(msg)
        uat_row = await session.get(GuardrailCatalogue, uat_id)
        if uat_row is None:
            logger.warning("UAT guardrail %s not found for demote (orphaned prod copy).", uat_id)
            return 0, uat_id
    else:
        uat_row = row
        uat_id = guardrail_id

    uat_row.prod_ref_count = max((uat_row.prod_ref_count or 0) - 1, 0)
    session.add(uat_row)
    await session.commit()
    await session.refresh(uat_row)

    logger.info(
        "Guardrail prod ref count decremented: uat_id=%s, new_count=%d",
        uat_id, uat_row.prod_ref_count,
    )
    return uat_row.prod_ref_count, uat_id


async def get_sync_status(
    session: AsyncSession,
    guardrail_id: UUID,
) -> dict:
    """Compare UAT guardrail with its prod copy and return sync status."""
    uat_row = await session.get(GuardrailCatalogue, guardrail_id)
    if uat_row is None:
        msg = f"Guardrail {guardrail_id} not found."
        raise ValueError(msg)

    if uat_row.environment != "uat":
        msg = f"Guardrail {guardrail_id} is not a UAT guardrail."
        raise ValueError(msg)

    prod_row = await _get_prod_copy(session, guardrail_id)

    if prod_row is None:
        return {
            "has_prod_copy": False,
            "prod_guardrail_id": None,
            "in_sync": False,
            "uat_updated_at": uat_row.updated_at,
            "prod_promoted_at": None,
            "prod_ref_count": uat_row.prod_ref_count,
        }

    uat_hash = _runtime_config_hash(uat_row.runtime_config)
    prod_hash = _runtime_config_hash(prod_row.runtime_config)

    return {
        "has_prod_copy": True,
        "prod_guardrail_id": str(prod_row.id),
        "in_sync": uat_hash == prod_hash,
        "uat_updated_at": uat_row.updated_at,
        "prod_promoted_at": prod_row.promoted_at,
        "prod_ref_count": uat_row.prod_ref_count,
    }


async def resolve_prod_guardrail_id(
    session: AsyncSession,
    uat_guardrail_id: UUID,
) -> UUID | None:
    """Given a UAT guardrail ID, return the prod copy's ID (or None)."""
    prod_row = await _get_prod_copy(session, uat_guardrail_id)
    return prod_row.id if prod_row else None
