"""Guardrails service module.

NeMo guardrail execution has been moved to the guardrails-service microservice.
The backend now delegates all guardrail operations via HTTP through
`agentcore.services.guardrail_service_client`.

This module retains only the lightweight `is_nemo_runtime_config_ready` helper
used by the catalogue API for local validation before proxying to the service.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


def is_nemo_runtime_config_ready(
    runtime_config: dict[str, Any] | None,
    model_registry_id: UUID | str | None = None,
) -> bool:
    """Check locally whether a NeMo guardrail runtime config is minimally complete.

    This mirrors the logic in the guardrails-service so the backend can validate
    payloads before sending them to the microservice, without a round-trip.
    """
    if not model_registry_id:
        return False
    if not isinstance(runtime_config, dict):
        return False
    for key in ("config_yml", "configYml", "config.yml"):
        value = runtime_config.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in {".", "..."}:
            return True
    return False


__all__ = ["is_nemo_runtime_config_ready"]
