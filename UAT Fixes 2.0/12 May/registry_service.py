"""CRUD operations for the guardrail_catalogue table and versioning."""

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
from app.models.guardrail_version import (
    GuardrailVersion,
    GuardrailVersionRead,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VERSIONING_FIELDS = (
    "name",
    "description",
    "category",
    "model_registry_id",
    "runtime_config",
)


def _versioning_spec_from_row(row: GuardrailCatalogue) -> dict:
    spec = {f: getattr(row, f, None) for f in _VERSIONING_FIELDS}
    if spec["model_registry_id"] is not None:
        spec["model_registry_id"] = str(spec["model_registry_id"])
    return spec


def _versioning_spec_from_snapshot(snapshot: dict | None) -> dict:
    snapshot = snapshot or {}
    spec = {f: snapshot.get(f) for f in _VERSIONING_FIELDS}
    if spec["model_registry_id"] is not None:
        spec["model_registry_id"] = str(spec["model_registry_id"])
    return spec


def _versioning_hash(spec: dict | None) -> str:
    """Deterministic hash over the identity fields that define a guardrail version."""
    if not spec:
        return ""
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, default=str).encode()
    ).hexdigest()


def _snapshot_guardrail(row: GuardrailCatalogue) -> dict:
    """Create a frozen snapshot dict from a guardrail catalogue row."""
    return {
        "name": row.name,
        "description": row.description,
        "framework": row.framework,
        "provider": row.provider,
        "model_registry_id": str(row.model_registry_id) if row.model_registry_id else None,
        "category": row.category,
        "status": row.status,
        "rules_count": row.rules_count,
        "is_custom": row.is_custom,
        "runtime_config": row.runtime_config,
        "visibility": row.visibility,
        "public_scope": row.public_scope,
        "shared_user_ids": row.shared_user_ids,
        "public_dept_ids": row.public_dept_ids,
    }


async def _get_next_version_number(
    session: AsyncSession,
    guardrail_id: UUID,
) -> int:
    """Calculate the next version number for a guardrail (max existing + 1)."""
    stmt = select(GuardrailVersion.version_number).where(
        GuardrailVersion.guardrail_id == guardrail_id,
    )
    results = (await session.execute(stmt)).scalars().all()
    if not results:
        return 1
    return max(results) + 1


async def _get_active_version(
    session: AsyncSession,
    guardrail_id: UUID,
) -> GuardrailVersion | None:
    """Get the current active version for a guardrail."""
    stmt = (
        select(GuardrailVersion)
        .where(
            GuardrailVersion.guardrail_id == guardrail_id,
            GuardrailVersion.is_active.is_(True),
        )
        .order_by(GuardrailVersion.version_number.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


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

    Guardrails are always editable — versioning is handled via guardrail_version
    snapshots created during agent deployment.
    """
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
    """Hard-delete a guardrail entry. Returns True if the row existed.

    Guardrails with active production versions cannot be deleted.
    """
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        return False

    # Check for active versions
    active_version = await _get_active_version(session, guardrail_id)
    if active_version is not None:
        msg = (
            f"Cannot delete guardrail '{row.name}' — it has an active "
            f"production version (v{active_version.version_number}). "
            "Deactivate the version or remove the production agents first."
        )
        raise ValueError(msg)

    await session.delete(row)
    await session.commit()
    return True


async def list_active_prod_guardrails(
    session: AsyncSession,
    *,
    framework: str | None = None,
) -> list[GuardrailCatalogueRead]:
    """Return one synthesized row per guardrail that has an active prod version.

    Mutable identity fields (name/description/category/model_registry_id/runtime_config)
    are overlaid from the active version's frozen snapshot so the PROD view does not
    reflect later UAT edits.
    """
    stmt = select(GuardrailCatalogue).where(GuardrailCatalogue.latest_version > 0)
    if framework:
        stmt = stmt.where(GuardrailCatalogue.framework == framework)
    stmt = stmt.order_by(GuardrailCatalogue.name.asc())
    rows = (await session.execute(stmt)).scalars().all()

    out: list[GuardrailCatalogueRead] = []
    for row in rows:
        active = await _get_active_version(session, row.id)
        if active is None:
            continue
        snap = active.guardrail_snapshot or {}
        read = GuardrailCatalogueRead.from_orm_model(row)
        overlay: dict[str, object] = {}
        for field in _VERSIONING_FIELDS:
            if field not in snap:
                continue
            value = snap[field]
            if field == "model_registry_id" and value is not None:
                try:
                    value = UUID(str(value))
                except (TypeError, ValueError):
                    value = None
            overlay[field] = value
        if overlay:
            read = read.model_copy(update=overlay)
        out.append(read)
    return out


async def get_active_nemo_guardrails(session: AsyncSession) -> list[GuardrailCatalogueRead]:
    """Return all active NeMo guardrails that have a model_registry_id set.

    Returns the editable draft entries from guardrail_catalogue.
    """
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


# ---------------------------------------------------------------------------
# Versioning & Promotion
# ---------------------------------------------------------------------------


async def promote_guardrail(
    session: AsyncSession,
    guardrail_id: UUID,
    promoted_by: UUID,
) -> tuple[GuardrailVersionRead, bool]:
    """Create a new version of a guardrail during agent deployment to prod.

    Snapshots the current guardrail config into a guardrail_version row.
    If the config hasn't changed since the last active version, reuses it
    (idempotent). Otherwise creates a new version (v1, v2, v3...).

    Returns ``(version_read, in_sync)`` where *in_sync* indicates whether
    the existing active version was already up-to-date.
    """
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        msg = f"Guardrail {guardrail_id} not found."
        raise ValueError(msg)

    now = datetime.now(timezone.utc)
    current_hash = _versioning_hash(_versioning_spec_from_row(row))

    # Check if active version already matches current identity fields
    active_version = await _get_active_version(session, guardrail_id)
    if active_version is not None:
        active_hash = _versioning_hash(
            _versioning_spec_from_snapshot(active_version.guardrail_snapshot)
        )
        if current_hash == active_hash:
            logger.info(
                "Guardrail promotion idempotent (already in sync): "
                "guardrail_id=%s, active_version=v%d",
                guardrail_id, active_version.version_number,
            )
            return GuardrailVersionRead.from_orm_model(active_version), True

    # Config has changed — create new version
    next_version = await _get_next_version_number(session, guardrail_id)
    snapshot = _snapshot_guardrail(row)

    # Deactivate previous active version
    if active_version is not None:
        active_version.is_active = False
        active_version.updated_at = now
        session.add(active_version)

    new_version = GuardrailVersion(
        guardrail_id=guardrail_id,
        org_id=row.org_id,
        dept_id=row.dept_id,
        version_number=next_version,
        guardrail_snapshot=snapshot,
        guardrail_name=row.name,
        is_active=True,
        status="PUBLISHED",
        created_by=promoted_by,
        created_at=now,
        updated_at=now,
    )
    session.add(new_version)

    # Update latest_version on catalogue
    row.latest_version = next_version
    session.add(row)

    await session.commit()
    await session.refresh(new_version)

    logger.info(
        "Guardrail promoted (new version): guardrail_id=%s, version=v%d",
        guardrail_id, next_version,
    )
    return GuardrailVersionRead.from_orm_model(new_version), False


async def demote_guardrail(
    session: AsyncSession,
    guardrail_id: UUID,
) -> tuple[int, UUID]:
    """Deactivate the active version when a prod deployment is removed.

    Returns ``(version_number, guardrail_id)``.
    """
    active_version = await _get_active_version(session, guardrail_id)
    if active_version is None:
        logger.warning("No active version found for guardrail %s during demote.", guardrail_id)
        return 0, guardrail_id

    active_version.is_active = False
    active_version.updated_at = datetime.now(timezone.utc)
    session.add(active_version)
    await session.commit()

    logger.info(
        "Guardrail version deactivated: guardrail_id=%s, version=v%d",
        guardrail_id, active_version.version_number,
    )
    return active_version.version_number, guardrail_id


async def get_sync_status(
    session: AsyncSession,
    guardrail_id: UUID,
) -> dict:
    """Compare current guardrail draft with its latest active version."""
    row = await session.get(GuardrailCatalogue, guardrail_id)
    if row is None:
        msg = f"Guardrail {guardrail_id} not found."
        raise ValueError(msg)

    active_version = await _get_active_version(session, guardrail_id)

    if active_version is None:
        return {
            "has_active_version": False,
            "guardrail_version_id": None,
            "version_number": 0,
            "in_sync": False,
            "draft_updated_at": row.updated_at,
            "version_created_at": None,
            "latest_version": row.latest_version,
        }

    draft_hash = _versioning_hash(_versioning_spec_from_row(row))
    version_hash = _versioning_hash(
        _versioning_spec_from_snapshot(active_version.guardrail_snapshot)
    )

    return {
        "has_active_version": True,
        "guardrail_version_id": str(active_version.id),
        "version_number": active_version.version_number,
        "in_sync": draft_hash == version_hash,
        "draft_updated_at": row.updated_at,
        "version_created_at": active_version.created_at,
        "latest_version": row.latest_version,
    }


# ---------------------------------------------------------------------------
# Version queries
# ---------------------------------------------------------------------------


async def get_guardrail_versions(
    session: AsyncSession,
    guardrail_id: UUID,
) -> list[GuardrailVersionRead]:
    """Return all versions for a guardrail, ordered by version_number desc."""
    stmt = (
        select(GuardrailVersion)
        .where(GuardrailVersion.guardrail_id == guardrail_id)
        .order_by(GuardrailVersion.version_number.desc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [GuardrailVersionRead.from_orm_model(r) for r in rows]


async def get_guardrail_version_by_id(
    session: AsyncSession,
    version_id: UUID,
) -> GuardrailVersionRead | None:
    """Return a specific guardrail version by its ID."""
    row = await session.get(GuardrailVersion, version_id)
    if row is None:
        return None
    return GuardrailVersionRead.from_orm_model(row)
