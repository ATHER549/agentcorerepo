"""HTTP client for the Guardrails microservice.

Bridges the agentcore backend to the standalone Guardrails microservice by
proxying:
  - Guardrail catalogue CRUD operations
  - NeMo guardrail execution (apply)
  - Cache invalidation
  - Active guardrails listing (for the flow component dropdown)
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)

# Default timeout for guardrail execution (NeMo can be slow when initialising LLM)
_DEFAULT_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _get_guardrails_service_settings() -> tuple[str, str]:
    """Get Guardrails service URL and API key from agentcore settings."""
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    url = getattr(settings, "guardrails_service_url", "")
    api_key = getattr(settings, "guardrails_service_api_key", "")

    if not url:
        msg = "GUARDRAILS_SERVICE_URL is not configured. Set it in your environment or .env file."
        raise ValueError(msg)

    return url.rstrip("/"), api_key or ""


def _headers(api_key: str) -> dict[str, str]:
    """Build standard headers for Guardrails service requests."""
    h = {"Content-Type": "application/json"}
    if api_key:
        h["x-api-key"] = api_key
    return h


def is_service_configured() -> bool:
    """Check whether the Guardrails service URL is configured (non-empty)."""
    try:
        _get_guardrails_service_settings()
        return True
    except (ValueError, Exception):
        return False


# ---------------------------------------------------------------------------
# Guardrail catalogue CRUD proxies
# ---------------------------------------------------------------------------


async def fetch_guardrails_async(
    framework: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch all guardrail catalogue entries from the microservice."""
    url, api_key = _get_guardrails_service_settings()
    params: dict[str, str] = {}
    if framework:
        params["framework"] = framework
    if status:
        params["status"] = status

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{url}/v1/guardrails",
            headers=_headers(api_key),
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_guardrail_via_service(guardrail_id: str | UUID) -> dict[str, Any]:
    """Fetch a single guardrail from the microservice by ID."""
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{url}/v1/guardrails/{guardrail_id}",
            headers=_headers(api_key),
        )
        resp.raise_for_status()
        return resp.json()


async def create_guardrail_via_service(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a new guardrail in the catalogue via the microservice."""
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{url}/v1/guardrails",
            headers=_headers(api_key),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def update_guardrail_via_service(
    guardrail_id: str | UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing guardrail in the catalogue via the microservice."""
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.patch(
            f"{url}/v1/guardrails/{guardrail_id}",
            headers=_headers(api_key),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def delete_guardrail_via_service(guardrail_id: str | UUID) -> None:
    """Delete a guardrail from the catalogue via the microservice."""
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(
            f"{url}/v1/guardrails/{guardrail_id}",
            headers=_headers(api_key),
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# NeMo guardrail execution proxy
# ---------------------------------------------------------------------------


async def apply_nemo_guardrail_via_service(
    input_text: str,
    guardrail_id: str,
    environment: str | None = None,
) -> dict[str, Any]:
    """Apply a NeMo guardrail to input_text via the microservice.

    When *environment* is ``"prod"``, the microservice resolves the frozen
    production copy of the guardrail (via ``source_guardrail_id``).

    Returns a dict with keys:
      output_text, action, guardrail_id,
      input_tokens, output_tokens, total_tokens,
      llm_calls_count, model, provider
    """
    url, api_key = _get_guardrails_service_settings()
    payload: dict[str, Any] = {"input_text": input_text, "guardrail_id": guardrail_id}
    if environment:
        payload["environment"] = environment
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            f"{url}/v1/guardrails/apply",
            headers=_headers(api_key),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Guardrail promotion (UAT → PROD)
# ---------------------------------------------------------------------------


async def promote_guardrail_via_service(
    guardrail_id: str | UUID,
    promoted_by: str | UUID,
) -> dict[str, Any]:
    """Promote a UAT guardrail to production via the microservice.

    Creates a frozen prod copy (or reuses an existing one). Increments
    ``prod_ref_count`` on the UAT record.

    Returns a dict with keys: prod_guardrail_id, source_guardrail_id,
    promoted_at, in_sync.
    """
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{url}/v1/guardrails/{guardrail_id}/promote",
            headers=_headers(api_key),
            json={"promoted_by": str(promoted_by)},
        )
        resp.raise_for_status()
        return resp.json()


async def demote_guardrail_via_service(
    guardrail_id: str | UUID,
) -> dict[str, Any]:
    """Decrement prod_ref_count when a production deployment is removed.

    Returns a dict with keys: source_guardrail_id, prod_ref_count.
    """
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{url}/v1/guardrails/{guardrail_id}/demote",
            headers=_headers(api_key),
            json={},
        )
        resp.raise_for_status()
        return resp.json()


async def get_guardrail_sync_status_via_service(
    guardrail_id: str | UUID,
) -> dict[str, Any]:
    """Get sync status between a UAT guardrail and its prod copy.

    Returns a dict with keys: has_prod_copy, prod_guardrail_id, in_sync,
    uat_updated_at, prod_promoted_at, prod_ref_count.
    """
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{url}/v1/guardrails/{guardrail_id}/sync-status",
            headers=_headers(api_key),
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Active guardrails listing (for flow component dropdown)
# ---------------------------------------------------------------------------


async def list_active_guardrails_via_service(
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch the list of active NeMo guardrails from the microservice.

    Each item has: id (str UUID), name (str), runtime_ready (bool),
    plus tenancy fields for RBAC filtering.

    When *user_id* is provided, results are filtered by the user's
    org/department memberships (same logic as the Guardrails Catalogue page).
    """
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{url}/v1/guardrails/active",
            headers=_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("guardrails", [])

    if user_id:
        from agentcore.components.models._rbac_helpers import filter_guardrails_by_rbac

        items = filter_guardrails_by_rbac(items, user_id)

    return items


# ---------------------------------------------------------------------------
# Cache invalidation proxies
# ---------------------------------------------------------------------------


async def invalidate_guardrail_cache_via_service(guardrail_id: str | UUID) -> None:
    """Ask the microservice to invalidate the NeMo rails cache for a guardrail."""
    url, api_key = _get_guardrails_service_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{url}/v1/guardrails/{guardrail_id}/invalidate-cache",
                headers=_headers(api_key),
            )
            resp.raise_for_status()
            logger.debug("Guardrail cache invalidated via service: guardrail_id=%s", guardrail_id)
    except Exception:  # noqa: BLE001
        # Cache invalidation is best-effort; log but do not propagate
        logger.warning(
            "Guardrail cache invalidation via service failed (non-fatal): guardrail_id=%s",
            guardrail_id,
            exc_info=True,
        )


async def clear_all_guardrail_cache_via_service() -> None:
    """Ask the microservice to clear the entire NeMo rails cache."""
    url, api_key = _get_guardrails_service_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{url}/v1/guardrails/cache",
                headers=_headers(api_key),
            )
            resp.raise_for_status()
            logger.debug("All guardrail cache cleared via service")
    except Exception:  # noqa: BLE001
        logger.warning("Clearing all guardrail cache via service failed (non-fatal)", exc_info=True)
