"""Scope resolution for observability API — wraps the RBAC service."""

import hashlib
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.database.models.user.model import User
from agentcore.services.observability import (
    ObservabilityScopeError,
    resolve_observability_scope,
)
from agentcore.services.observability import get_langfuse_provisioning_service  # noqa: F401 – re-export

from .langfuse_client import get_langfuse_client_for_binding


async def resolve_scope_context(
    *,
    session: AsyncSession,
    current_user: User,
    org_id: UUID | None = None,
    dept_id: UUID | None = None,
    enforce_filter_for_admin: bool = True,
) -> tuple[set[str], list[Any], str, list[str]]:
    """Resolve RBAC scope into (allowed_user_ids, langfuse_clients, scope_key, warnings)."""
    try:
        resolution = await resolve_observability_scope(
            session,
            current_user=current_user,
            org_id=org_id,
            dept_id=dept_id,
            enforce_filter_for_admin=enforce_filter_for_admin,
        )
    except ObservabilityScopeError as exc:
        detail = str(exc)
        status_code = 403 if "outside your" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    clients: list[Any] = []
    failed_binding_ids: list[str] = []
    for binding in resolution.bindings:
        client = get_langfuse_client_for_binding(binding)
        if client is not None:
            clients.append(client)
        else:
            failed_binding_ids.append(str(binding.id))

    scope_warnings: list[str] = []
    if not resolution.bindings:
        scope_warnings.append(
            "No active Langfuse bindings are configured for the selected scope."
        )
    elif not clients:
        scope_warnings.append(
            "Langfuse bindings exist for this scope, but none are usable. "
            "Check encrypted keys/host connectivity."
        )
    elif failed_binding_ids:
        scope_warnings.append(
            f"{len(failed_binding_ids)} binding(s) could not be initialized for this scope."
        )

    sorted_uids = sorted(resolution.allowed_user_ids)
    user_hash = (
        hashlib.sha256("|".join(sorted_uids).encode()).hexdigest()[:12]
        if sorted_uids
        else "none"
    )
    scope_key = f"{resolution.role}:{resolution.org_id}:{resolution.dept_id}:{user_hash}"
    return resolution.allowed_user_ids, clients, scope_key, scope_warnings


def scope_warning_payload(scope_warnings: list[str]) -> dict[str, Any]:
    if not scope_warnings:
        return {"scope_warning": False, "scope_warning_message": None}
    return {
        "scope_warning": True,
        "scope_warning_message": " ".join(scope_warnings),
    }
