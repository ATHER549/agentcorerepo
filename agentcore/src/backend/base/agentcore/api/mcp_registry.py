"""REST endpoints for the MCP server registry."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services import mcp_registry_service
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.mcp_registry.model import (
    McpProbeResponse,
    McpRegistry,
    McpRegistryCreate,
    McpRegistryRead,
    McpRegistryUpdate,
    McpTestConnectionRequest,
    McpTestConnectionResponse,
    McpToolInfo,
)
from agentcore.services.database.models.mcp_approval_request.model import McpApprovalRequest
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/registry", tags=["MCP Registry"])


class McpRequestPayload(McpRegistryCreate):
    """Payload used by developer/business users to request MCP access."""


def _normalize_visibility(value: str | None) -> str:
    normalized = (value or "private").strip().lower()
    if normalized not in {"private", "public"}:
        raise HTTPException(status_code=400, detail=f"Unsupported visibility '{value}'")
    return normalized


def _normalize_public_scope(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"organization", "department"}:
        raise HTTPException(status_code=400, detail=f"Unsupported public_scope '{value}'")
    return normalized


def _normalize_deployment_env(value: str | None) -> str:
    normalized = (value or "DEV").strip().upper()
    if normalized == "TEST":
        normalized = "DEV"
    if normalized not in {"DEV", "UAT", "PROD"}:
        raise HTTPException(status_code=400, detail=f"Unsupported deployment_env '{value}'")
    return normalized


def _string_ids(values: list[UUID] | None) -> list[str]:
    return [str(v) for v in (values or [])]


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    return str(getattr(current_user, "role", "")).lower() == "root"


async def _require_mcp_permission(current_user: CurrentActiveUser, permission: str) -> None:
    user_permissions = await get_permissions_for_role(str(current_user.role))
    if permission not in user_permissions:
        raise HTTPException(status_code=403, detail="Missing required permissions")


async def _require_any_mcp_permission(current_user: CurrentActiveUser, permissions: set[str]) -> None:
    user_permissions = set(await get_permissions_for_role(str(current_user.role)))
    if not user_permissions.intersection(permissions):
        raise HTTPException(status_code=403, detail="Missing required permissions")


async def _get_scope_memberships(session: DbSession, user_id: UUID) -> tuple[set[UUID], list[tuple[UUID, UUID]]]:
    org_rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    dept_rows = (
        await session.exec(
            select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    org_ids = {r if isinstance(r, UUID) else r[0] for r in org_rows}
    return org_ids, [(row[0], row[1]) for row in dept_rows]


async def _validate_scope_refs(session: DbSession, org_id: UUID | None, dept_id: UUID | None) -> None:
    if dept_id and not org_id:
        raise HTTPException(status_code=400, detail="dept_id requires org_id")
    if org_id:
        org = await session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=400, detail="Invalid org_id")
    if dept_id:
        dept = (
            await session.exec(
                select(Department).where(Department.id == dept_id, Department.org_id == org_id)
            )
        ).first()
        if not dept:
            raise HTTPException(status_code=400, detail="Invalid dept_id for org_id")


async def _resolve_user_ids_by_emails(session: DbSession, emails: list[str]) -> list[str]:
    if not emails:
        return []
    normalized = [e.strip().lower() for e in emails if e and e.strip()]
    if not normalized:
        return []
    rows = (await session.exec(select(User.id, User.email).where(User.email.in_(normalized)))).all()
    found = {str(r[1]).lower(): str(r[0]) for r in rows}
    missing = [e for e in normalized if e not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"Invalid shared_user_emails: {', '.join(missing)}")
    return [found[e] for e in normalized]


async def _validate_departments_exist_for_org(session: DbSession, org_id: UUID, dept_ids: list[UUID]) -> None:
    if not dept_ids:
        return
    rows = (
        await session.exec(select(Department.id).where(Department.org_id == org_id, Department.id.in_(dept_ids)))
    ).all()
    if len({str(r if isinstance(r, UUID) else r[0]) for r in rows}) != len({str(d) for d in dept_ids}):
        raise HTTPException(status_code=400, detail="One or more public_dept_ids are invalid for org_id")


async def _ensure_mcp_name_available(
    session: DbSession,
    server_name: str,
    *,
    exclude_id: UUID | None = None,
) -> None:
    stmt = select(McpRegistry.id).where(
        func.lower(McpRegistry.server_name) == server_name.strip().lower(),
    )
    if exclude_id:
        stmt = stmt.where(McpRegistry.id != exclude_id)
    existing = (await session.exec(stmt)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="MCP server name already exists")


async def _enforce_creation_scope(
    session: DbSession,
    current_user: CurrentActiveUser,
    payload: McpRegistryCreate | McpRegistryUpdate,
) -> tuple[str, str | None, list[str], list[str]]:
    user_role = normalize_role(str(current_user.role))
    visibility = _normalize_visibility(getattr(payload, "visibility", None))
    public_scope = _normalize_public_scope(getattr(payload, "public_scope", None))
    public_dept_ids = _string_ids(getattr(payload, "public_dept_ids", None))
    shared_user_ids: list[str] = []
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)

    if user_role not in {"root", "super_admin", "department_admin", "developer", "business_user"}:
        raise HTTPException(status_code=403, detail="Your role is not allowed to manage MCP servers")

    if visibility == "private":
        payload.public_scope = None
        payload.public_dept_ids = None
        if user_role == "department_admin":
            if not dept_pairs:
                raise HTTPException(status_code=403, detail="No active department scope found")
            current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
            payload.org_id = current_org_id
            payload.dept_id = current_dept_id
            shared_user_ids = await _resolve_user_ids_by_emails(
                session,
                getattr(payload, "shared_user_emails", None) or [],
            )
            if shared_user_ids:
                allowed_ids = set(
                    str(v if isinstance(v, UUID) else v[0])
                    for v in (
                        await session.exec(
                            select(UserDepartmentMembership.user_id).where(
                                UserDepartmentMembership.department_id == current_dept_id,
                                UserDepartmentMembership.status == "active",
                            )
                        )
                    ).all()
                )
                if not set(shared_user_ids).issubset(allowed_ids):
                    raise HTTPException(
                        status_code=403,
                        detail="shared_user_emails must belong to your current department",
                    )
        else:
            if user_role in {"developer", "business_user"} and dept_pairs:
                current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
                payload.org_id = current_org_id
                payload.dept_id = current_dept_id
            else:
                payload.org_id = None
                payload.dept_id = None
    else:
        if public_scope is None:
            raise HTTPException(status_code=400, detail="public_scope is required when visibility is public")
        if public_scope == "organization":
            if not payload.org_id:
                raise HTTPException(status_code=400, detail="org_id is required for public organization visibility")
            if user_role != "root" and payload.org_id not in org_ids:
                raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
            payload.dept_id = None
            payload.public_dept_ids = None
            public_dept_ids = []
        else:
            if user_role in {"super_admin", "root"}:
                if not payload.org_id:
                    raise HTTPException(status_code=400, detail="org_id is required for department visibility")
                if user_role != "root" and payload.org_id not in org_ids:
                    raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
                if not public_dept_ids and payload.dept_id:
                    public_dept_ids = [str(payload.dept_id)]
                if not public_dept_ids:
                    raise HTTPException(status_code=400, detail="Select at least one department")
                await _validate_departments_exist_for_org(session, payload.org_id, [UUID(v) for v in public_dept_ids])
                payload.dept_id = UUID(public_dept_ids[0]) if len(public_dept_ids) == 1 else None
            else:
                if not dept_pairs:
                    raise HTTPException(status_code=403, detail="No active department scope found")
                current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
                payload.org_id = current_org_id
                payload.dept_id = current_dept_id
                public_dept_ids = [str(current_dept_id)]
        shared_user_ids = []

    await _validate_scope_refs(session, payload.org_id, payload.dept_id)
    return visibility, public_scope, public_dept_ids, shared_user_ids


def _can_access_server(
    row: McpRegistry,
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return (
            str(getattr(row, "created_by_id", "")) == str(current_user.id)
            and row.org_id is None
            and row.dept_id is None
        )

    role = normalize_role(str(current_user.role))
    if role == "super_admin" and row.org_id and row.org_id in org_ids:
        return True

    # Keep requester/approver visibility for pending/rejected requests.
    if (row.approval_status or "approved") != "approved":
        return row.requested_by == current_user.id or row.request_to == current_user.id

    visibility = _normalize_visibility(getattr(row, "visibility", "private"))
    user_id = str(current_user.id)
    dept_id_set = {str(dept_id) for _, dept_id in dept_pairs}

    if visibility == "private":
        return (
            str(row.created_by_id) == user_id
            or row.created_by == getattr(current_user, "username", None)
            or user_id in set(row.shared_user_ids or [])
        )
    if getattr(row, "public_scope", None) == "organization":
        return bool(row.org_id and row.org_id in org_ids)
    if getattr(row, "public_scope", None) == "department":
        dept_candidates = set(row.public_dept_ids or [])
        if row.dept_id:
            dept_candidates.add(str(row.dept_id))
        return bool(dept_candidates.intersection(dept_id_set))
    return False


async def _resolve_request_approver(
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None,
    dept_id: UUID | None,
) -> UUID:
    # Requests are always routed to department admin from requester's department.
    target_dept_id = dept_id
    if not target_dept_id:
        _, dept_pairs = await _get_scope_memberships(session, current_user.id)
        if not dept_pairs:
            raise HTTPException(status_code=403, detail="No active department scope found for requester")
        _, target_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
    dept = await session.get(Department, target_dept_id)
    if not dept or not dept.admin_user_id:
        raise HTTPException(status_code=400, detail="No department admin configured for requester department")
    return dept.admin_user_id


async def _resolve_super_admin_approver(
    session: DbSession,
    current_user: CurrentActiveUser,
) -> UUID:
    stmt = select(User).where(User.role == "super_admin", User.id != current_user.id).order_by(User.create_at.asc())
    row = (await session.exec(stmt)).first()
    if not row:
        raise HTTPException(status_code=400, detail="No Super Admin approver available")
    return row.id


def _requires_super_admin_mcp_approval(*, deployment_env: str, visibility: str, public_scope: str | None) -> bool:
    normalized_env = _normalize_deployment_env(deployment_env)
    normalized_visibility = _normalize_visibility(visibility)
    normalized_public_scope = _normalize_public_scope(public_scope)
    return normalized_env == "PROD" or (
        normalized_visibility == "public" and normalized_public_scope == "organization"
    )


@router.get("/", response_model=list[McpRegistryRead])
async def list_mcp_servers(
    session: DbSession,
    current_user: CurrentActiveUser,
    active_only: bool = False,
):
    """List MCP servers visible to the current user based on tenancy + approval state."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    stmt = select(McpRegistry).order_by(McpRegistry.server_name)
    rows = (await session.exec(stmt)).all()
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    visible_rows = [row for row in rows if _can_access_server(row, current_user, org_ids, dept_pairs)]
    if active_only:
        visible_rows = [r for r in visible_rows if bool(r.is_active)]
    return [McpRegistryRead.from_orm_model(r) for r in visible_rows]


@router.get("/visibility-options")
async def get_mcp_visibility_options(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_mcp_permission(current_user, "view_mcp_page")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    role = normalize_role(str(current_user.role))

    organizations = []
    if role == "root":
        org_rows = (await session.exec(select(Organization.id, Organization.name))).all()
        organizations = [{"id": str(r[0]), "name": r[1]} for r in org_rows]
    elif org_ids:
        org_rows = (
            await session.exec(select(Organization.id, Organization.name).where(Organization.id.in_(list(org_ids))))
        ).all()
        organizations = [{"id": str(r[0]), "name": r[1]} for r in org_rows]

    dept_ids = {dept_id for _, dept_id in dept_pairs}
    departments = []
    if role == "root":
        dept_rows = (await session.exec(select(Department.id, Department.name, Department.org_id))).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]
    elif role == "super_admin" and org_ids:
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id).where(Department.org_id.in_(list(org_ids)))
            )
        ).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]
    elif dept_ids:
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id).where(Department.id.in_(list(dept_ids)))
            )
        ).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]

    private_share_users = []
    if role == "department_admin" and dept_ids:
        primary_dept = sorted(dept_ids, key=str)[0]
        user_rows = (
            await session.exec(
                select(User.id, User.email)
                .join(UserDepartmentMembership, UserDepartmentMembership.user_id == User.id)
                .where(
                    UserDepartmentMembership.department_id == primary_dept,
                    UserDepartmentMembership.status == "active",
                    User.email.is_not(None),
                )
            )
        ).all()
        private_share_users = [{"id": str(r[0]), "email": r[1]} for r in user_rows if r[1]]

    return {
        "organizations": organizations,
        "departments": departments,
        "private_share_users": private_share_users,
        "role": role,
    }


@router.post("/", response_model=McpRegistryRead, status_code=201)
async def create_mcp_server(
    body: McpRegistryCreate,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Register a new MCP server directly (admin flows)."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "add_new_mcp")

    visibility, public_scope, public_dept_ids, shared_user_ids = await _enforce_creation_scope(session, current_user, body)
    await _ensure_mcp_name_available(session, body.server_name)
    body.deployment_env = _normalize_deployment_env(getattr(body, "deployment_env", None))
    now = datetime.now(timezone.utc)
    user_role = normalize_role(str(current_user.role))
    body.visibility = visibility
    body.public_scope = public_scope
    body.public_dept_ids = [UUID(v) for v in public_dept_ids] if public_dept_ids else None
    body.shared_user_ids = shared_user_ids
    body.created_by = current_user.username
    body.created_by_id = current_user.id
    body.requested_by = current_user.id
    body.requested_at = now
    requires_super_admin = _requires_super_admin_mcp_approval(
        deployment_env=body.deployment_env,
        visibility=visibility,
        public_scope=public_scope,
    )
    auto_approve = user_role in {"root", "super_admin"} or (
        user_role == "department_admin" and not requires_super_admin
    )

    if auto_approve:
        body.request_to = None
        body.reviewed_at = now
        body.reviewed_by = current_user.id
        body.approval_status = "approved"
        body.is_active = True
        body.status = "connected"
        return await mcp_registry_service.create_server(session, body)

    approver_id = await _resolve_super_admin_approver(session, current_user)
    body.request_to = approver_id
    body.reviewed_at = None
    body.reviewed_by = None
    body.approval_status = "pending"
    body.is_active = False
    body.status = "pending_approval"
    created = await mcp_registry_service.create_server(session, body)

    approval = McpApprovalRequest(
        mcp_id=UUID(str(created.id)),
        org_id=body.org_id,
        dept_id=body.dept_id,
        requested_by=current_user.id,
        request_to=approver_id,
        requested_at=now,
        deployment_env=body.deployment_env,
    )
    session.add(approval)
    await session.commit()
    return created


@router.post("/request", response_model=McpRegistryRead, status_code=201)
async def request_mcp_server(
    body: McpRequestPayload,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Request a new MCP server (developer/business_user flows)."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "request_new_mcp")
    role = normalize_role(str(current_user.role))
    if role not in {"developer", "business_user"}:
        raise HTTPException(status_code=403, detail="Only developer/business_user can create MCP requests")

    visibility, public_scope, public_dept_ids, shared_user_ids = await _enforce_creation_scope(session, current_user, body)
    await _ensure_mcp_name_available(session, body.server_name)
    deployment_env = _normalize_deployment_env(getattr(body, "deployment_env", None))
    now = datetime.now(timezone.utc)

    body.deployment_env = deployment_env
    body.visibility = visibility
    body.public_scope = public_scope
    body.public_dept_ids = [UUID(v) for v in public_dept_ids] if public_dept_ids else None
    body.shared_user_ids = shared_user_ids
    body.created_by = current_user.username
    body.created_by_id = current_user.id
    body.requested_by = current_user.id
    body.requested_at = now

    # Mirror model workflow:
    # - DEV + private => auto-approved
    # - otherwise request approval based on env/scope
    if deployment_env == "DEV" and visibility == "private":
        body.request_to = None
        body.reviewed_at = now
        body.reviewed_by = current_user.id
        body.approval_status = "approved"
        body.is_active = True
        body.status = "connected"
        return await mcp_registry_service.create_server(session, body)

    if _requires_super_admin_mcp_approval(
        deployment_env=deployment_env,
        visibility=visibility,
        public_scope=public_scope,
    ):
        approver_id = await _resolve_super_admin_approver(session, current_user)
    else:
        approver_id = await _resolve_request_approver(session, current_user, body.org_id, body.dept_id)
    body.request_to = approver_id
    body.reviewed_at = None
    body.reviewed_by = None
    body.approval_status = "pending"
    body.is_active = False
    body.status = "pending_approval"
    created = await mcp_registry_service.create_server(session, body)

    approval = McpApprovalRequest(
        mcp_id=UUID(str(created.id)),
        org_id=body.org_id,
        dept_id=body.dept_id,
        requested_by=current_user.id,
        request_to=approver_id,
        requested_at=now,
        deployment_env=deployment_env,
    )
    session.add(approval)
    await session.commit()
    return created


@router.get("/{server_id}", response_model=McpRegistryRead)
async def get_mcp_server(
    server_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Get a single MCP server by ID."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    server = await session.get(McpRegistry, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_server(server, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="MCP server is outside your visibility scope")
    return McpRegistryRead.from_orm_model(server)


@router.put("/{server_id}", response_model=McpRegistryRead)
async def update_mcp_server(
    server_id: UUID,
    body: McpRegistryUpdate,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Update an existing MCP server."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "add_new_mcp")
    row = await session.get(McpRegistry, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_server(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="MCP server is outside your visibility scope")

    if body.org_id is None:
        body.org_id = row.org_id
    if body.dept_id is None and body.public_scope != "organization":
        body.dept_id = row.dept_id
    if body.visibility is None:
        body.visibility = row.visibility
    if body.public_scope is None:
        body.public_scope = row.public_scope
    if body.public_dept_ids is None:
        body.public_dept_ids = [UUID(v) for v in (row.public_dept_ids or [])]
    if body.deployment_env is None:
        body.deployment_env = row.deployment_env
    else:
        body.deployment_env = _normalize_deployment_env(body.deployment_env)

    visibility, public_scope, public_dept_ids, shared_user_ids = await _enforce_creation_scope(session, current_user, body)
    if body.server_name:
        await _ensure_mcp_name_available(session, body.server_name, exclude_id=server_id)
    body.visibility = visibility
    body.public_scope = public_scope
    body.public_dept_ids = [UUID(v) for v in public_dept_ids] if public_dept_ids else None
    body.shared_user_ids = shared_user_ids
    body.reviewed_by = row.reviewed_by
    body.requested_by = row.requested_by
    body.request_to = row.request_to

    server = await mcp_registry_service.update_server(session, server_id, body)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Delete a registered MCP server."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_mcp_permission(current_user, "add_new_mcp")
    row = await session.get(McpRegistry, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_server(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="MCP server is outside your visibility scope")
    deleted = await mcp_registry_service.delete_server(session, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP server not found")


@router.post("/test-connection", response_model=McpTestConnectionResponse)
async def test_mcp_connection(
    body: McpTestConnectionRequest,
    current_user: CurrentActiveUser,
):
    """Test connectivity to an MCP server and return the number of tools discovered."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    await _require_any_mcp_permission(current_user, {"add_new_mcp", "request_new_mcp"})
    try:
        from agentcore.base.mcp.util import update_tools

        server_config: dict = {}
        if body.mode == "sse":
            if body.url:
                server_config["url"] = body.url
            if body.headers:
                server_config["headers"] = body.headers
        elif body.mode == "stdio":
            if body.command:
                server_config["command"] = body.command
            if body.args:
                server_config["args"] = body.args

        if body.env_vars:
            server_config["env"] = body.env_vars

        _, tool_list, _ = await update_tools(
            server_name="test-connection",
            server_config=server_config,
        )

        return McpTestConnectionResponse(
            success=True,
            message=f"Connected successfully. Found {len(tool_list)} tool(s).",
            tools_count=len(tool_list),
        )
    except Exception as e:
        logger.warning("MCP test connection failed: %s", e)
        return McpTestConnectionResponse(success=False, message=str(e))


@router.post("/{server_id}/probe", response_model=McpProbeResponse)
async def probe_mcp_server(
    server_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Probe a registered MCP server: test connectivity and discover tools."""
    await _require_mcp_permission(current_user, "view_mcp_page")
    row = await session.get(McpRegistry, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_server(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="MCP server is outside your visibility scope")
    if (row.approval_status or "approved") != "approved":
        raise HTTPException(status_code=400, detail="MCP server request is not approved yet")

    try:
        from agentcore.base.mcp.util import update_tools

        result = await mcp_registry_service.get_decrypted_config_by_id(session, server_id)
        if result is None:
            raise HTTPException(status_code=404, detail="MCP server not found or inactive")

        server_name, server_config = result

        _, tool_list, _ = await update_tools(
            server_name=server_name,
            server_config=server_config,
        )

        tools_info = [McpToolInfo(name=t.name, description=t.description or "") for t in tool_list]
        now = datetime.now(timezone.utc)
        row.status = "connected"
        row.updated_at = now
        session.add(row)
        await session.commit()

        return McpProbeResponse(
            success=True,
            message=f"Connected successfully. Found {len(tool_list)} tool(s).",
            tools_count=len(tool_list),
            tools=tools_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        now = datetime.now(timezone.utc)
        row.status = "error"
        row.updated_at = now
        session.add(row)
        await session.commit()
        logger.warning("MCP probe failed for server %s: %s", server_id, e)
        return McpProbeResponse(success=False, message=str(e))
