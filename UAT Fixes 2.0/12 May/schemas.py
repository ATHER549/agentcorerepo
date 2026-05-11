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
    guardrail_version_id: str | None = None  # version-pinned execution


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
# Guardrail promotion (versioned)
# ---------------------------------------------------------------------------


class PromoteGuardrailRequest(BaseModel):
    """Request to promote a guardrail (create a new version during agent deployment)."""

    promoted_by: str


class PromoteGuardrailResponse(BaseModel):
    """Result of promoting a guardrail — includes version info."""

    guardrail_version_id: str
    guardrail_id: str
    version_number: int
    in_sync: bool
    created_at: datetime


class DemoteGuardrailRequest(BaseModel):
    """Request to deactivate the active version when a prod deployment is removed."""

    pass


class DemoteGuardrailResponse(BaseModel):
    """Result of demoting a guardrail version."""

    guardrail_id: str
    version_number: int


# ---------------------------------------------------------------------------
# Guardrail sync status (draft vs active version)
# ---------------------------------------------------------------------------


class GuardrailSyncStatusResponse(BaseModel):
    """Sync status between guardrail draft and its active production version."""

    has_active_version: bool
    guardrail_version_id: str | None = None
    version_number: int = 0
    in_sync: bool
    draft_updated_at: datetime | None = None
    version_created_at: datetime | None = None
    latest_version: int = 0


# ---------------------------------------------------------------------------
# Guardrail version listing
# ---------------------------------------------------------------------------


class GuardrailVersionResponse(BaseModel):
    """A single guardrail version entry."""

    id: str
    guardrail_id: str
    version_number: int
    guardrail_name: str
    guardrail_snapshot: dict[str, Any]
    is_active: bool
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class GuardrailVersionListResponse(BaseModel):
    """List of guardrail versions."""

    versions: list[GuardrailVersionResponse]
