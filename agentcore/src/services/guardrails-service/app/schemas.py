"""OpenAI-compatible and guardrail-specific request/response DTOs."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Apply guardrail
# ---------------------------------------------------------------------------


class ApplyGuardrailRequest(BaseModel):
    """Request to apply a NeMo guardrail to an input text."""

    input_text: str
    guardrail_id: str


class ApplyGuardrailResponse(BaseModel):
    """Result of applying a NeMo guardrail."""

    output_text: str
    action: str  # "passthrough" | "blocked" | "rewritten"
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


class ActiveGuardrailsResponse(BaseModel):
    guardrails: list[ActiveGuardrailItem]


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


class CacheInvalidateResponse(BaseModel):
    message: str
