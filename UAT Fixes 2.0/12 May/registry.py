"""REST endpoints for the guardrail catalogue (CRUD) and versioning."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.database import get_session
from app.models.guardrail_catalogue import (
    GuardrailCatalogueCreate,
    GuardrailCatalogueRead,
    GuardrailCatalogueUpdate,
)
from app.schemas import (
    DemoteGuardrailResponse,
    GuardrailSyncStatusResponse,
    GuardrailVersionListResponse,
    GuardrailVersionResponse,
    PromoteGuardrailRequest,
    PromoteGuardrailResponse,
)
from app.services import registry_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/guardrails", tags=["guardrail-registry"])


@router.get("", response_model=list[GuardrailCatalogueRead])
@router.get("/", response_model=list[GuardrailCatalogueRead])
async def list_guardrails(
    framework: str | None = None,
    status: str | None = None,
    environment: str | None = None,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """List guardrail catalogue entries.

    When ``environment=prod``, returns only guardrails that have an active
    production version, with mutable identity fields overlaid from the
    frozen snapshot. Otherwise returns the live UAT/draft rows.
    """
    if environment == "prod":
        return await registry_service.list_active_prod_guardrails(
            session, framework=framework,
        )
    if environment not in (None, "uat"):
        raise HTTPException(status_code=400, detail=f"Unsupported environment: {environment}")
    return await registry_service.get_guardrails(session, framework=framework, status=status)


@router.post("", response_model=GuardrailCatalogueRead, status_code=201)
@router.post("/", response_model=GuardrailCatalogueRead, status_code=201)
async def create_guardrail(
    body: GuardrailCatalogueCreate,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Create a new guardrail in the catalogue."""
    return await registry_service.create_guardrail(session, body)


@router.get("/{guardrail_id}", response_model=GuardrailCatalogueRead)
async def get_guardrail(
    guardrail_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Get a single guardrail by ID."""
    guardrail = await registry_service.get_guardrail(session, guardrail_id)
    if guardrail is None:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    return guardrail


@router.patch("/{guardrail_id}", response_model=GuardrailCatalogueRead)
async def update_guardrail(
    guardrail_id: UUID,
    body: GuardrailCatalogueUpdate,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Update an existing guardrail in the catalogue.

    Guardrails are always editable. Versioning is handled via snapshots
    created during agent deployment.
    """
    try:
        guardrail = await registry_service.update_guardrail(session, guardrail_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if guardrail is None:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    return guardrail


@router.delete("/{guardrail_id}", status_code=204)
async def delete_guardrail(
    guardrail_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Delete a guardrail from the catalogue.

    Guardrails with active production versions cannot be deleted — returns 409.
    """
    try:
        deleted = await registry_service.delete_guardrail(session, guardrail_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Guardrail not found")


# ---------------------------------------------------------------------------
# Promotion (versioned)
# ---------------------------------------------------------------------------


@router.post("/{guardrail_id}/promote", response_model=PromoteGuardrailResponse)
async def promote_guardrail(
    guardrail_id: UUID,
    body: PromoteGuardrailRequest,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Promote a guardrail by creating a new versioned snapshot.

    Called automatically during agent deployment to production.
    If the guardrail config hasn't changed since the last version, reuses it.
    """
    try:
        promoted_by = UUID(body.promoted_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid promoted_by UUID: {body.promoted_by}") from exc

    try:
        version_read, in_sync = await registry_service.promote_guardrail(session, guardrail_id, promoted_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PromoteGuardrailResponse(
        guardrail_version_id=str(version_read.id),
        guardrail_id=str(guardrail_id),
        version_number=version_read.version_number,
        in_sync=in_sync,
        created_at=version_read.created_at,
    )


@router.post("/{guardrail_id}/demote", response_model=DemoteGuardrailResponse)
async def demote_guardrail(
    guardrail_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Deactivate the active version when a production deployment is removed."""
    try:
        version_number, gid = await registry_service.demote_guardrail(session, guardrail_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DemoteGuardrailResponse(
        guardrail_id=str(gid),
        version_number=version_number,
    )


# ---------------------------------------------------------------------------
# Sync status (draft vs active version)
# ---------------------------------------------------------------------------


@router.get("/{guardrail_id}/sync-status", response_model=GuardrailSyncStatusResponse)
async def get_sync_status(
    guardrail_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Compare a guardrail draft with its active production version."""
    try:
        status = await registry_service.get_sync_status(session, guardrail_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return GuardrailSyncStatusResponse(**status)


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------


@router.get("/{guardrail_id}/versions", response_model=GuardrailVersionListResponse)
async def list_guardrail_versions(
    guardrail_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """List all versions for a guardrail, ordered by version number descending."""
    versions = await registry_service.get_guardrail_versions(session, guardrail_id)
    return GuardrailVersionListResponse(
        versions=[
            GuardrailVersionResponse(
                id=str(v.id),
                guardrail_id=str(v.guardrail_id),
                version_number=v.version_number,
                guardrail_name=v.guardrail_name,
                guardrail_snapshot=v.guardrail_snapshot,
                is_active=v.is_active,
                status=v.status,
                created_by=str(v.created_by),
                created_at=v.created_at,
                updated_at=v.updated_at,
            )
            for v in versions
        ]
    )


@router.get("/{guardrail_id}/versions/{version_id}", response_model=GuardrailVersionResponse)
async def get_guardrail_version(
    guardrail_id: UUID,
    version_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Get a specific guardrail version by ID."""
    version = await registry_service.get_guardrail_version_by_id(session, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Guardrail version not found")
    if version.guardrail_id != guardrail_id:
        raise HTTPException(status_code=404, detail="Guardrail version not found for this guardrail")

    return GuardrailVersionResponse(
        id=str(version.id),
        guardrail_id=str(version.guardrail_id),
        version_number=version.version_number,
        guardrail_name=version.guardrail_name,
        guardrail_snapshot=version.guardrail_snapshot,
        is_active=version.is_active,
        status=version.status,
        created_by=str(version.created_by),
        created_at=version.created_at,
        updated_at=version.updated_at,
    )
