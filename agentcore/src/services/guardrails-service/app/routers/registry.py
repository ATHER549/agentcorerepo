"""REST endpoints for the guardrail catalogue (CRUD)."""

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
from app.services import registry_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/guardrails", tags=["guardrail-registry"])


@router.get("", response_model=list[GuardrailCatalogueRead])
@router.get("/", response_model=list[GuardrailCatalogueRead])
async def list_guardrails(
    framework: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """List all guardrail catalogue entries, optionally filtered by framework or status."""
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
    """Update an existing guardrail in the catalogue."""
    guardrail = await registry_service.update_guardrail(session, guardrail_id, body)
    if guardrail is None:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    return guardrail


@router.delete("/{guardrail_id}", status_code=204)
async def delete_guardrail(
    guardrail_id: UUID,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Delete a guardrail from the catalogue."""
    deleted = await registry_service.delete_guardrail(session, guardrail_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Guardrail not found")
