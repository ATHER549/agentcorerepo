"""REST endpoints for NeMo guardrail execution and cache management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.database import get_session
from app.models.guardrail_catalogue import GuardrailCatalogue
from app.models.model_registry import ModelRegistry
from app.schemas import (
    ActiveGuardrailItem,
    ActiveGuardrailsResponse,
    ApplyGuardrailRequest,
    ApplyGuardrailResponse,
    CacheInvalidateResponse,
)
from app.services import nemo_service, registry_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/guardrails", tags=["guardrail-execution"])


# ---------------------------------------------------------------------------
# Apply guardrail
# ---------------------------------------------------------------------------


@router.post("/apply", response_model=ApplyGuardrailResponse)
async def apply_guardrail(
    body: ApplyGuardrailRequest,
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """Apply a NeMo guardrail to the provided input text.

    Returns the result including whether the content was blocked, passed
    through, or rewritten, along with token usage metrics.
    """
    try:
        result = await nemo_service.apply_nemo_guardrail_text(
            input_text=body.input_text,
            guardrail_id=body.guardrail_id,
            session=session,
            environment=body.environment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return ApplyGuardrailResponse(
        output_text=result.output_text,
        action=result.action,
        guardrail_id=result.guardrail_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        llm_calls_count=result.llm_calls_count,
        model=result.model,
        provider=result.provider,
    )


# ---------------------------------------------------------------------------
# Active guardrails listing (for flow component dropdown)
# ---------------------------------------------------------------------------


@router.get("/active", response_model=ActiveGuardrailsResponse)
async def list_active_guardrails(
    session: AsyncSession = Depends(get_session),
    _api_key: str = Depends(verify_api_key),
):
    """List active NeMo guardrails with their runtime-readiness status.

    Used by the NeMo Guardrails flow component to populate the dropdown.
    Only returns guardrails with framework='nemo', status='active', and a
    model_registry_id set. Validates that the linked model registry entry
    is also active.
    """
    guardrails = await registry_service.get_active_nemo_guardrails(session)
    if not guardrails:
        return ActiveGuardrailsResponse(guardrails=[])

    # Filter to only guardrails whose model_registry entry is also active
    model_ids = list({g.model_registry_id for g in guardrails if g.model_registry_id})
    active_model_ids: set[str] = set()
    if model_ids:
        result = await session.execute(
            select(ModelRegistry.id).where(
                ModelRegistry.id.in_(model_ids),
                ModelRegistry.is_active.is_(True),
            )
        )
        active_model_ids = {str(row[0]) for row in result.all()}

    items: list[ActiveGuardrailItem] = []
    for g in guardrails:
        if g.model_registry_id and str(g.model_registry_id) not in active_model_ids:
            continue
        runtime_ready = nemo_service.is_nemo_runtime_config_ready(g.runtime_config, g.model_registry_id)
        items.append(
            ActiveGuardrailItem(
                id=str(g.id),
                name=g.name,
                runtime_ready=runtime_ready,
                visibility=g.visibility,
                org_id=str(g.org_id) if g.org_id else None,
                dept_id=str(g.dept_id) if g.dept_id else None,
                created_by=str(g.created_by) if g.created_by else None,
                public_scope=g.public_scope,
                public_dept_ids=g.public_dept_ids,
            )
        )

    return ActiveGuardrailsResponse(guardrails=items)


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


@router.post("/{guardrail_id}/invalidate-cache", response_model=CacheInvalidateResponse)
async def invalidate_guardrail_cache(
    guardrail_id: UUID,
    _api_key: str = Depends(verify_api_key),
):
    """Invalidate the NeMo rails cache for a specific guardrail.

    Called by the backend whenever a guardrail is created, updated, or deleted
    to ensure the next execution picks up the latest configuration.
    """
    removed = nemo_service.invalidate_nemo_guardrail_cache(guardrail_id)
    if removed:
        return CacheInvalidateResponse(message=f"Cache invalidated for guardrail {guardrail_id}")
    return CacheInvalidateResponse(message=f"No cache entry found for guardrail {guardrail_id}")


@router.delete("/cache", response_model=CacheInvalidateResponse)
async def clear_all_guardrail_cache(
    _api_key: str = Depends(verify_api_key),
):
    """Clear the entire NeMo rails cache (all guardrails)."""
    count = nemo_service.clear_nemo_guardrails_cache()
    return CacheInvalidateResponse(message=f"Cleared {count} cached guardrail rail(s)")
