from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, distinct
from sqlmodel import select

from agentcore.api.utils import DbSession
from agentcore.api.schemas import (
    PermissionReadResponse,
    RoleCreateRequest,
    RoleReadResponse,
    RoleUpdateRequest,
)
from agentcore.services.auth.decorators import PermissionChecker
from agentcore.services.auth.permissions import (
    PERMISSION_ALIASES,
    invalidate_role_permissions_cache,
    normalize_role,
)
from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.permission import Permission
from agentcore.services.database.models.role import Role
from agentcore.services.database.models.role_permission import RolePermission
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.database.models.user.model import User


router = APIRouter(tags=["Roles"], prefix="/roles")
ACTIVE_ORG_STATUSES = {"accepted", "active"}
ACTIVE_DEPT_STATUS = "active"


def _normalize_role_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


@router.get(
    "/permissions",
    response_model=list[PermissionReadResponse],
    dependencies=[Depends(PermissionChecker(["view_access_control_page"]))],
)
async def list_permissions(
    session: DbSession,
    current_user: User = Depends(get_current_active_user),
) -> list[Permission]:
    _ensure_access_control_actor(current_user)
    permissions = (await session.exec(select(Permission).order_by(Permission.name))).all()
    return permissions


@router.get(
    "/",
    response_model=list[RoleReadResponse],
    dependencies=[Depends(PermissionChecker(["view_access_control_page"]))],
)
async def list_roles(
    session: DbSession,
    current_user: User = Depends(get_current_active_user),
) -> list[RoleReadResponse]:
    _ensure_access_control_actor(current_user)
    roles = await _get_roles_in_scope(session, current_user)

    response: list[RoleReadResponse] = []
    for role in roles:
        response.append(
            RoleReadResponse(
                id=role.id,
                name=role.name,
                display_name=role.display_name,
                description=role.description,
                parent_role_id=role.parent_role_id,
                is_system=role.is_system,
                is_active=role.is_active,
                permissions=await _get_effective_permissions_for_role(session, role),
            )
        )
    return response


@router.post(
    "/",
    response_model=RoleReadResponse,
    dependencies=[Depends(PermissionChecker(["view_access_control_page"]))],
)
async def create_role(
    payload: RoleCreateRequest,
    session: DbSession,
    current_user: User = Depends(get_current_active_user),
) -> RoleReadResponse:
    _ensure_access_control_actor(current_user)
    if normalize_role(current_user.role) == "super_admin":
        org_ids = await _admin_org_ids(session, current_user)
        if not org_ids:
            raise HTTPException(status_code=403, detail="Super admin has no organization scope.")

    name = _normalize_role_name(payload.name)
    existing = (await session.exec(select(Role).where(Role.name == name))).first()
    if existing:
        raise HTTPException(status_code=409, detail="Role name already exists")

    role = Role(
        name=name,
        display_name=payload.display_name or payload.name,
        description=payload.description,
        parent_role_id=payload.parent_role_id,
        is_system=False,
        is_active=True if payload.is_active is None else payload.is_active,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(role)
    await session.commit()
    await session.refresh(role)

    if payload.permissions:
        await _replace_role_permissions(session, role.id, payload.permissions)
        await invalidate_role_permissions_cache(role.name)

    return RoleReadResponse(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        parent_role_id=role.parent_role_id,
        is_system=role.is_system,
        is_active=role.is_active,
        permissions=await _get_effective_permissions_for_role(session, role),
    )


@router.patch(
    "/{role_id}",
    response_model=RoleReadResponse,
    dependencies=[Depends(PermissionChecker(["view_access_control_page"]))],
)
async def update_role(
    role_id: UUID,
    payload: RoleUpdateRequest,
    session: DbSession,
    current_user: User = Depends(get_current_active_user),
) -> RoleReadResponse:
    _ensure_access_control_actor(current_user)
    role = await session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    await _assert_role_in_scope(session, current_user, role)
    if role.is_system and payload.name and _normalize_role_name(payload.name) != role.name:
        raise HTTPException(status_code=400, detail="System roles cannot be renamed")

    if payload.name:
        role.name = _normalize_role_name(payload.name)
    if payload.display_name is not None:
        role.display_name = payload.display_name
    if payload.description is not None:
        role.description = payload.description
    if payload.parent_role_id is not None:
        role.parent_role_id = payload.parent_role_id
    if payload.is_active is not None:
        role.is_active = payload.is_active
    role.updated_by = current_user.id

    session.add(role)
    await session.commit()
    await session.refresh(role)

    if payload.permissions is not None:
        await _replace_role_permissions(session, role.id, payload.permissions)
        await invalidate_role_permissions_cache(role.name)

    return RoleReadResponse(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        parent_role_id=role.parent_role_id,
        is_system=role.is_system,
        is_active=role.is_active,
        permissions=await _get_effective_permissions_for_role(session, role),
    )


@router.put(
    "/{role_id}/permissions",
    response_model=RoleReadResponse,
    dependencies=[Depends(PermissionChecker(["view_access_control_page"]))],
)
async def replace_role_permissions(
    role_id: UUID,
    permissions: list[str],
    session: DbSession,
    current_user: User = Depends(get_current_active_user),
) -> RoleReadResponse:
    _ensure_access_control_actor(current_user)
    role = await session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    await _assert_role_in_scope(session, current_user, role)

    await _replace_role_permissions(session, role.id, permissions)
    await invalidate_role_permissions_cache(role.name)
    return RoleReadResponse(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        parent_role_id=role.parent_role_id,
        is_system=role.is_system,
        is_active=role.is_active,
        permissions=await _get_effective_permissions_for_role(session, role),
    )


@router.delete(
    "/{role_id}",
    dependencies=[Depends(PermissionChecker(["view_access_control_page"]))],
)
async def delete_role(
    role_id: UUID,
    session: DbSession,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    _ensure_access_control_actor(current_user)
    role = await session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    await _assert_role_in_scope(session, current_user, role)
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")

    users_with_role = (await session.exec(select(User).where(User.role == role.name))).first()
    if users_with_role:
        raise HTTPException(status_code=400, detail="Role is in use by existing users")

    # delete role permissions
    await session.exec(delete(RolePermission).where(RolePermission.role_id == role.id))
    await session.delete(role)
    await session.commit()
    return {"detail": "Role deleted"}


async def _replace_role_permissions(session: DbSession, role_id: UUID, permissions: list[str]) -> None:
    unique_permissions = list(dict.fromkeys(permissions))
    if not unique_permissions:
        # Remove existing
        await session.exec(delete(RolePermission).where(RolePermission.role_id == role_id))
        await session.commit()
        return

    perm_rows = (
        await session.exec(select(Permission).where(Permission.key.in_(unique_permissions)))
    ).all()
    found_keys = {perm.key for perm in perm_rows}
    missing_keys = [key for key in unique_permissions if key not in found_keys]
    if missing_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown permissions: {', '.join(missing_keys)}",
        )

    # Remove existing only after validation succeeds.
    await session.exec(delete(RolePermission).where(RolePermission.role_id == role_id))
    for perm in perm_rows:
        session.add(RolePermission(role_id=role_id, permission_id=perm.id))
    await session.commit()


async def _get_permissions_for_role(session: DbSession, role_id: UUID) -> list[str]:
    rows = (await session.exec(select(RolePermission).where(RolePermission.role_id == role_id))).all()
    if not rows:
        return []
    perm_ids = [row.permission_id for row in rows]
    perm_rows = (await session.exec(select(Permission).where(Permission.id.in_(perm_ids)))).all()
    return [p.key for p in perm_rows]


def _expand_permissions(perms: list[str]) -> list[str]:
    expanded: list[str] = []
    for perm in perms:
        if perm not in expanded:
            expanded.append(perm)
        for alias in PERMISSION_ALIASES.get(perm, []):
            if alias not in expanded:
                expanded.append(alias)
    return expanded


async def _get_effective_permissions_for_role(session: DbSession, role: Role) -> list[str]:
    direct_permissions = await _get_permissions_for_role(session, role.id)
    if direct_permissions:
        return _expand_permissions(direct_permissions)
    return []


async def _admin_org_ids(session: DbSession, current_user: User) -> set[UUID]:
    role = normalize_role(current_user.role)
    if role == "root":
        return set((await session.exec(select(Organization.id))).all())
    rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
        )
    ).all()
    return set(rows)


async def _org_user_ids(session: DbSession, org_ids: set[UUID]) -> set[UUID]:
    if not org_ids:
        return set()
    rows = (
        await session.exec(
            select(distinct(UserOrganizationMembership.user_id)).where(
                UserOrganizationMembership.org_id.in_(list(org_ids)),
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
        )
    ).all()
    return set(rows)


async def _roles_used_in_org(session: DbSession, org_ids: set[UUID]) -> set[UUID]:
    if not org_ids:
        return set()
    org_role_rows = (
        await session.exec(
            select(distinct(UserOrganizationMembership.role_id)).where(
                UserOrganizationMembership.org_id.in_(list(org_ids)),
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
        )
    ).all()
    dept_role_rows = (
        await session.exec(
            select(distinct(UserDepartmentMembership.role_id)).where(
                UserDepartmentMembership.org_id.in_(list(org_ids)),
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
            )
        )
    ).all()
    return set(org_role_rows) | set(dept_role_rows)


async def _get_roles_in_scope(session: DbSession, current_user: User) -> list[Role]:
    actor_role = normalize_role(current_user.role)
    if actor_role == "root":
        roles = (await session.exec(select(Role).order_by(Role.name))).all()
        return [role for role in roles if normalize_role(role.name) != "root"]
    if actor_role != "super_admin":
        return []

    org_ids = await _admin_org_ids(session, current_user)
    if not org_ids:
        return []
    org_user_ids = await _org_user_ids(session, org_ids)
    org_role_ids = await _roles_used_in_org(session, org_ids)

    roles = (await session.exec(select(Role).order_by(Role.name))).all()
    scoped_roles: list[Role] = []
    for role in roles:
        if normalize_role(role.name) == "root":
            continue
        if role.is_system:
            continue
        if role.created_by and role.created_by in org_user_ids:
            scoped_roles.append(role)
            continue
        if role.id in org_role_ids:
            scoped_roles.append(role)
    return scoped_roles


async def _assert_role_in_scope(session: DbSession, current_user: User, role: Role) -> None:
    actor_role = normalize_role(current_user.role)
    if normalize_role(role.name) == "root":
        raise HTTPException(status_code=403, detail="Root role is system-managed and not configurable.")

    if actor_role == "root":
        return

    if actor_role != "super_admin":
        raise HTTPException(status_code=403, detail="Insufficient scope for role management.")

    scoped_roles = await _get_roles_in_scope(session, current_user)
    if not any(r.id == role.id for r in scoped_roles):
        raise HTTPException(status_code=403, detail="Role is outside your organization scope.")


def _ensure_access_control_actor(current_user: User) -> None:
    if normalize_role(current_user.role) != "root":
        raise HTTPException(status_code=403, detail="Access Control is restricted to root users only.")
