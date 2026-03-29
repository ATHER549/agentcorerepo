"""Shared RBAC helpers for registry component files (LLM + Embeddings).

Provides user-membership queries and visibility-scope filtering so that
agent-builder dropdowns only show models the current user is allowed to see,
and build-time checks prevent unauthorized model usage.
"""

from __future__ import annotations

import asyncio
import os
import threading
from uuid import UUID

from loguru import logger

# ---------------------------------------------------------------------------
# Sync / async bridges
# ---------------------------------------------------------------------------

_sync_engine = None
_sync_engine_lock = threading.Lock()


def _get_sync_engine():
    """Return a dedicated synchronous SQLAlchemy engine (created once)."""
    global _sync_engine
    if _sync_engine is not None:
        return _sync_engine

    with _sync_engine_lock:
        if _sync_engine is not None:
            return _sync_engine

        from sqlalchemy import create_engine

        from agentcore.services.deps import get_db_service

        db_service = get_db_service()
        db_url = db_service.database_url
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "")

        _sync_engine = create_engine(db_url, pool_pre_ping=True, pool_size=3)
        logger.info(f"Created dedicated sync engine for registry RBAC: {db_url.split('@')[-1]}")
        return _sync_engine


def _run_async(coro):
    """Run an async coroutine from a synchronous context, handling existing event loops."""
    import concurrent.futures as _cf

    try:
        asyncio.get_running_loop()
        with _cf.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# User identity helpers
# ---------------------------------------------------------------------------


def resolve_user_id(component) -> str | None:
    """Extract user_id string from a component instance."""
    raw = (
        getattr(component, "user_id", None)
        or getattr(getattr(component, "graph", None), "user_id", None)
        or ""
    )
    return str(raw).strip() or None


def _parse_uuid(val) -> UUID | None:
    if not val:
        return None
    try:
        return UUID(str(val))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# User membership queries
# ---------------------------------------------------------------------------


async def get_user_memberships_async(
    user_id_str: str,
) -> tuple[str, str, set[UUID], set[UUID]]:
    """Query user role, username, org_ids, dept_ids from DB (async).

    Returns ``(role, username, org_ids, dept_ids)`` — all normalised.
    """
    uid = _parse_uuid(user_id_str)
    if uid is None:
        return "", "", set(), set()

    from agentcore.services.deps import get_db_service

    db_service = get_db_service()

    async with db_service.with_session() as session:
        from sqlalchemy import select

        from agentcore.services.database.models.user.model import User
        from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
        from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership

        user_row = await session.get(User, uid)
        if user_row is None:
            return "", "", set(), set()

        role = str(getattr(user_row, "role", "") or "").strip().lower()
        username = str(getattr(user_row, "username", "") or "")

        org_rows = (
            await session.execute(
                select(UserOrganizationMembership.org_id).where(
                    UserOrganizationMembership.user_id == uid,
                    UserOrganizationMembership.status.in_(["accepted", "active"]),
                )
            )
        ).scalars().all()

        dept_rows = (
            await session.execute(
                select(UserDepartmentMembership.department_id).where(
                    UserDepartmentMembership.user_id == uid,
                    UserDepartmentMembership.status == "active",
                )
            )
        ).scalars().all()

        org_ids = {r for r in org_rows if r is not None}
        dept_ids = {r for r in dept_rows if r is not None}

        return role, username, org_ids, dept_ids


def get_user_memberships_sync(
    user_id_str: str,
) -> tuple[str, str, set[UUID], set[UUID]]:
    """Query user role, username, org_ids, dept_ids from DB (sync engine).

    Used in ``build_model()`` / ``build_embeddings()`` for defence-in-depth RBAC.
    """
    uid = _parse_uuid(user_id_str)
    if uid is None:
        return "", "", set(), set()

    from sqlalchemy.orm import Session

    from agentcore.services.database.models.user.model import User
    from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
    from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership

    engine = _get_sync_engine()
    with Session(engine) as session:
        user_row = session.get(User, uid)
        if user_row is None:
            return "", "", set(), set()

        role = str(getattr(user_row, "role", "") or "").strip().lower()
        username = str(getattr(user_row, "username", "") or "")

        org_ids = {
            r[0]
            for r in session.query(UserOrganizationMembership.org_id)
            .filter(
                UserOrganizationMembership.user_id == uid,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
            .all()
            if r and r[0] is not None
        }

        dept_ids = {
            r[0]
            for r in session.query(UserDepartmentMembership.department_id)
            .filter(
                UserDepartmentMembership.user_id == uid,
                UserDepartmentMembership.status == "active",
            )
            .all()
            if r and r[0] is not None
        }

        return role, username, org_ids, dept_ids


# ---------------------------------------------------------------------------
# RBAC checks — dict-based (operate on microservice response dicts)
# ---------------------------------------------------------------------------


def can_access_model_dict(
    d: dict,
    role: str,
    user_id_str: str,
    username: str,
    org_ids: set[UUID],
    dept_ids: set[UUID],
) -> bool:
    """Check if user can access a model dict based on RBAC rules.

    Mirrors ``_can_access_model()`` in ``api/model_registry.py`` but operates
    on plain dicts (from microservice JSON responses) instead of ORM rows.
    """
    if role == "root":
        return True

    model_org_id = _parse_uuid(d.get("org_id"))
    model_dept_id = _parse_uuid(d.get("dept_id"))
    public_dept_ids = {str(v) for v in (d.get("public_dept_ids") or [])}
    dept_id_strs = {str(v) for v in dept_ids}

    # Super-admin: org-scoped
    if role == "super_admin" and model_org_id and model_org_id in org_ids:
        return True

    # Department admin: dept-scoped
    if role == "department_admin":
        if model_dept_id and str(model_dept_id) in dept_id_strs:
            return True
        if public_dept_ids.intersection(dept_id_strs):
            return True

    # Unapproved models: only visible to requester / approver
    approval = (d.get("approval_status") or "approved").lower()
    if approval != "approved":
        return (
            str(d.get("requested_by") or "") == user_id_str
            or str(d.get("request_to") or "") == user_id_str
        )

    # Visibility scope filtering
    visibility = (d.get("visibility_scope") or "private").lower()

    if visibility == "private":
        return (
            str(d.get("created_by_id") or "") == user_id_str
            or str(d.get("requested_by") or "") == user_id_str
            or str(d.get("created_by") or "") == username
        )
    if visibility == "department":
        if model_dept_id and str(model_dept_id) in dept_id_strs:
            return True
        return bool(public_dept_ids.intersection(dept_id_strs))
    if visibility == "organization":
        return bool(model_org_id and model_org_id in org_ids)

    return False


def can_access_server_dict(
    d: dict,
    role: str,
    user_id_str: str,
    username: str,
    org_ids: set[UUID],
    dept_ids: set[UUID],
) -> bool:
    """Check if user can access an MCP server dict based on RBAC rules.

    Mirrors ``_can_access_server()`` in ``api/mcp_registry.py``.
    """
    server_org_id = _parse_uuid(d.get("org_id"))
    server_dept_id = _parse_uuid(d.get("dept_id"))

    # Root: only own servers without org/dept scope
    if role == "root":
        return (
            str(d.get("created_by_id") or "") == user_id_str
            and server_org_id is None
            and server_dept_id is None
        )

    # Super-admin: org-scoped
    if role == "super_admin" and server_org_id and server_org_id in org_ids:
        return True

    # Unapproved: only requester / approver
    approval = (d.get("approval_status") or "approved").lower()
    if approval != "approved":
        return (
            str(d.get("requested_by") or "") == user_id_str
            or str(d.get("request_to") or "") == user_id_str
        )

    visibility = (d.get("visibility") or "private").lower()
    dept_id_strs = {str(v) for v in dept_ids}

    if visibility == "private":
        shared = set(d.get("shared_user_ids") or [])
        return (
            str(d.get("created_by_id") or "") == user_id_str
            or str(d.get("created_by") or "") == username
            or user_id_str in shared
        )

    public_scope = d.get("public_scope")
    if public_scope == "organization":
        return bool(server_org_id and server_org_id in org_ids)
    if public_scope == "department":
        dept_candidates = set(d.get("public_dept_ids") or [])
        if server_dept_id:
            dept_candidates.add(str(server_dept_id))
        return bool(dept_candidates.intersection(dept_id_strs))

    return False


# ---------------------------------------------------------------------------
# RBAC checks — guardrail dicts
# ---------------------------------------------------------------------------


def can_access_guardrail_dict(
    d: dict,
    role: str,
    user_id_str: str,
    username: str,
    org_ids: set[UUID],
    dept_ids: set[UUID],
) -> bool:
    """Check if user can access a guardrail dict based on RBAC rules.

    Mirrors ``_can_access_guardrail()`` in ``api/guardrails_catalogue.py`` but
    operates on plain dicts (from microservice JSON responses).
    """
    row_org_id = _parse_uuid(d.get("org_id"))
    row_dept_id = _parse_uuid(d.get("dept_id"))
    row_created_by = str(d.get("created_by") or "")
    visibility = (d.get("visibility") or "private").strip().lower()
    public_scope = d.get("public_scope")
    public_dept_ids = set(d.get("public_dept_ids") or [])
    dept_id_strs = {str(v) for v in dept_ids}

    # Root user: only own guardrails without org/dept scope
    if role == "root":
        return (
            row_created_by == user_id_str
            and row_org_id is None
            and row_dept_id is None
        )

    # Super-admin: all guardrails in their org
    if role == "super_admin" and row_org_id and row_org_id in org_ids:
        return True

    # Private guardrails
    if visibility == "private":
        if role == "department_admin":
            return bool(row_dept_id and str(row_dept_id) in dept_id_strs)
        return row_created_by == user_id_str

    # Public — organization scope
    if public_scope == "organization":
        return bool(row_org_id and row_org_id in org_ids)

    # Public — department scope
    if public_scope == "department":
        dept_candidates = set(public_dept_ids)
        if row_dept_id:
            dept_candidates.add(str(row_dept_id))
        return bool(dept_candidates.intersection(dept_id_strs))

    return False


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def filter_models_by_rbac(models: list[dict], user_id_str: str | None) -> list[dict]:
    """Filter a list of model dicts by RBAC rules for the given user.

    Uses async DB query (via ``_run_async``) to fetch user memberships.
    Suitable for ``update_build_config()`` (dropdown population).
    """
    if not user_id_str:
        return models

    try:
        role, username, org_ids, dept_ids = _run_async(
            get_user_memberships_async(user_id_str)
        )
    except Exception as e:
        logger.warning(f"Failed to get user memberships for RBAC filtering: {e}")
        return models

    if role == "root":
        return models

    return [
        m
        for m in models
        if can_access_model_dict(m, role, user_id_str, username, org_ids, dept_ids)
    ]


def filter_guardrails_by_rbac(guardrails: list[dict], user_id_str: str | None) -> list[dict]:
    """Filter a list of guardrail dicts by RBAC rules for the given user.

    Uses async DB query (via ``_run_async``) to fetch user memberships.
    Suitable for ``update_build_config()`` (dropdown population).
    """
    if not user_id_str:
        return guardrails

    try:
        role, username, org_ids, dept_ids = _run_async(
            get_user_memberships_async(user_id_str)
        )
    except Exception as e:
        logger.warning(f"Failed to get user memberships for guardrail RBAC filtering: {e}")
        return guardrails

    return [
        g
        for g in guardrails
        if can_access_guardrail_dict(g, role, user_id_str, username, org_ids, dept_ids)
    ]


def check_model_access_sync(model_dict: dict, user_id_str: str | None) -> bool:
    """Check RBAC access for a single model (sync, for build-time).

    Uses the dedicated sync engine for user membership queries.
    """
    if not user_id_str:
        return True

    try:
        role, username, org_ids, dept_ids = get_user_memberships_sync(user_id_str)
    except Exception as e:
        logger.warning(f"Failed to get user memberships for RBAC check: {e}")
        return True  # fail open to avoid blocking builds when DB is unreachable

    if not role:
        return True  # user not found — fail open

    return can_access_model_dict(model_dict, role, user_id_str, username, org_ids, dept_ids)


def fetch_model_by_id_sync(model_id: str) -> dict | None:
    """Fetch a single model from the Model microservice (sync HTTP)."""
    import httpx

    from agentcore.services.model_service_client import _get_model_service_settings, _headers

    try:
        url, api_key = _get_model_service_settings()
    except ValueError:
        return None

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{url}/v1/registry/models/{model_id}",
                headers=_headers(api_key),
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch model {model_id} from microservice: {e}")
        return None
