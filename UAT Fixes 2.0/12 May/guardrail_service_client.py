"""HTTP client for the Guardrails microservice.

Bridges the agentcore backend to the standalone Guardrails microservice by
proxying:
  - Guardrail catalogue CRUD operations
  - NeMo guardrail execution (apply)
  - Cache invalidation
  - Active guardrails listing (for the flow component dropdown)
  - Guardrail versioning & promotion
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)

# Default timeout for guardrail execution (NeMo can be slow when initialising LLM)
_DEFAULT_TIMEOUT = 120.0


class GuardrailRateLimitError(Exception):
    """Raised when the Guardrails microservice returns HTTP 429.

    Carries the parsed error payload so the calling component can surface a
    specific user-facing message ("rate limit on guardrail model X")
    instead of falling back to the generic "blocked" message.

    ``error_code`` distinguishes:
      * ``"rate_limit_exceeded"`` -- guardrails-service's own pre-flight bucket
      * ``"guardrail_model_rate_limit"`` -- upstream model / provider 429
    """

    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        retry_after_seconds: int,
        provider: str | None = None,
        model: str | None = None,
        limit_type: str | None = None,
        limit: int | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.retry_after_seconds = retry_after_seconds
        self.provider = provider
        self.model = model
        self.limit_type = limit_type
        self.limit = limit
        super().__init__(message)


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
    environment: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch all guardrail catalogue entries from the microservice.

    When ``environment='prod'`` the microservice returns synthesized rows
    backed by the active version's frozen snapshot, so PROD view does not
    reflect later UAT edits.
    """
    url, api_key = _get_guardrails_service_settings()
    params: dict[str, str] = {}
    if framework:
        params["framework"] = framework
    if status:
        params["status"] = status
    if environment:
        params["environment"] = environment

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
    guardrail_version_id: str | None = None,
) -> dict[str, Any]:
    """Apply a NeMo guardrail to input_text via the microservice.

    When *guardrail_version_id* is provided, the microservice uses the
    frozen snapshot of that specific version (version-pinned execution).

    When *environment* is ``"prod"`` (legacy fallback), the microservice
    resolves the latest active version.

    Returns a dict with keys:
      output_text, action, guardrail_id,
      input_tokens, output_tokens, total_tokens,
      llm_calls_count, model, provider
    """
    url, api_key = _get_guardrails_service_settings()
    payload: dict[str, Any] = {"input_text": input_text, "guardrail_id": guardrail_id}
    if guardrail_version_id:
        payload["guardrail_version_id"] = guardrail_version_id
    elif environment:
        payload["environment"] = environment
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            f"{url}/v1/guardrails/apply",
            headers=_headers(api_key),
            json=payload,
        )
        if resp.status_code == 429:
            detail: dict[str, Any] = {}
            try:
                body = resp.json()
                raw_detail = body.get("detail") if isinstance(body, dict) else None
                if isinstance(raw_detail, dict):
                    detail = raw_detail
                elif isinstance(body, dict):
                    detail = body
            except Exception:  # noqa: BLE001
                detail = {}
            try:
                retry_after = int(
                    detail.get("retry_after_seconds")
                    or resp.headers.get("Retry-After")
                    or 30
                )
            except (TypeError, ValueError):
                retry_after = 30
            error_code = str(detail.get("error") or "rate_limit_exceeded")
            provider = detail.get("provider")
            model = detail.get("model")
            limit_type = detail.get("limit_type")
            limit = detail.get("limit")
            # Mirror the LLM ModelRateLimitError message shape so the
            # orchestrator chat renders both the same way (red alert card),
            # just with the "model being used in guardrail" hint.
            if limit_type and limit:
                limit_label = str(limit_type).upper()
                message = (
                    f"Rate limit exceeded for model being used in guardrail "
                    f"({limit_label} = {limit}/min). Try again in ~{retry_after}s."
                )
            elif error_code == "guardrail_model_rate_limit":
                model_label = f" ({provider}/{model})" if provider and model else ""
                message = (
                    f"Rate limit exceeded for model being used in guardrail"
                    f"{model_label}. Try again in ~{retry_after}s."
                )
            elif detail.get("message"):
                message = str(detail["message"])
            else:
                message = (
                    f"Rate limit exceeded for model being used in guardrail. "
                    f"Try again in ~{retry_after}s."
                )
            raise GuardrailRateLimitError(
                error_code=error_code,
                message=message,
                retry_after_seconds=retry_after,
                provider=provider,
                model=model,
                limit_type=limit_type,
                limit=limit,
            )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Guardrail promotion (versioned)
# ---------------------------------------------------------------------------


async def promote_guardrail_via_service(
    guardrail_id: str | UUID,
    promoted_by: str | UUID,
) -> dict[str, Any]:
    """Promote a guardrail by creating a new versioned snapshot.

    Called automatically during agent deployment to production.
    If the config hasn't changed since the last version, reuses it.

    Returns a dict with keys: guardrail_version_id, guardrail_id,
    version_number, in_sync, created_at.
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
    """Deactivate the active version when a production deployment is removed.

    Returns a dict with keys: guardrail_id, version_number.
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
    """Get sync status between guardrail draft and its active production version.

    Returns a dict with keys: has_active_version, guardrail_version_id,
    version_number, in_sync, draft_updated_at, version_created_at, latest_version.
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
# Guardrail version queries
# ---------------------------------------------------------------------------


async def get_guardrail_versions_via_service(
    guardrail_id: str | UUID,
) -> dict[str, Any]:
    """Fetch all versions for a guardrail from the microservice.

    Returns a dict with key: versions (list of version objects).
    """
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{url}/v1/guardrails/{guardrail_id}/versions",
            headers=_headers(api_key),
        )
        resp.raise_for_status()
        return resp.json()


async def get_guardrail_version_via_service(
    guardrail_id: str | UUID,
    version_id: str | UUID,
) -> dict[str, Any]:
    """Fetch a specific guardrail version from the microservice.

    Returns a dict with version details including the snapshot.
    """
    url, api_key = _get_guardrails_service_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{url}/v1/guardrails/{guardrail_id}/versions/{version_id}",
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
