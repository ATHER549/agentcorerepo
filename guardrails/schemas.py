"""OpenAI-compatible and guardrail-specific request/response DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Apply guardrail
# ---------------------------------------------------------------------------


class ApplyGuardrailRequest(BaseModel):
    """Request to apply a NeMo guardrail to an input text."""

    input_text: str
    guardrail_id: str
    environment: str | None = None  # "uat" or "prod"; None defaults to UAT lookup


class ApplyGuardrailResponse(BaseModel):
    """Result of applying a NeMo guardrail."""

    output_text: str
    action: str  # "passthrough" | "blocked" | "rewritten" | "masked"
    guardrail_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls_count: int = 0
    model: str | None = None
    provider: str | None = None


# ---------------------------------------------------------------------------
# Active guardrails listing (for flow component dropdown)
# ---------------------------------------------------------------------------


class ActiveGuardrailItem(BaseModel):
    """Represents one entry in the active guardrails dropdown."""

    id: str
    name: str
    runtime_ready: bool
    # Tenancy fields — used by agentcore for RBAC filtering
    visibility: str | None = None
    org_id: str | None = None
    dept_id: str | None = None
    created_by: str | None = None
    public_scope: str | None = None
    public_dept_ids: list[str] | None = None


class ActiveGuardrailsResponse(BaseModel):
    guardrails: list[ActiveGuardrailItem]


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


class CacheInvalidateResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Guardrail promotion (UAT → PROD)
# ---------------------------------------------------------------------------


class PromoteGuardrailRequest(BaseModel):
    """Request to promote a UAT guardrail to production."""

    promoted_by: str


class PromoteGuardrailResponse(BaseModel):
    """Result of promoting a guardrail to production."""

    prod_guardrail_id: str
    source_guardrail_id: str
    promoted_at: datetime
    in_sync: bool


class DemoteGuardrailRequest(BaseModel):
    """Request to decrement prod ref count when a prod deployment is removed."""

    pass


class DemoteGuardrailResponse(BaseModel):
    """Result of demoting a guardrail reference."""

    source_guardrail_id: str
    prod_ref_count: int


# ---------------------------------------------------------------------------
# Guardrail sync status (UAT vs PROD)
# ---------------------------------------------------------------------------


class GuardrailSyncStatusResponse(BaseModel):
    """Sync status between UAT guardrail and its prod copy."""

    has_prod_copy: bool
    prod_guardrail_id: str | None = None
    in_sync: bool
    uat_updated_at: datetime | None = None
    prod_promoted_at: datetime | None = None
    prod_ref_count: int = 0
