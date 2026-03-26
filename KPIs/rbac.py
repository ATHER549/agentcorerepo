from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import distinct
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.langfuse_binding.model import LangfuseBinding
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership


ACTIVE_ORG_STATUSES = {"accepted", "active"}
ACTIVE_DEPT_STATUS = "active"

DEPT_ADMIN_VISIBLE_ROLES = {"business_user", "developer"}
SUPER_ADMIN_VISIBLE_ROLES = {"department_admin", "business_user", "developer"}
ROOT_VISIBLE_ROLES = {"super_admin", "department_admin", "business_user", "developer"}


class ObservabilityScopeError(ValueError):
    """Raised when requested observability scope is invalid for the user."""


@dataclass
class ObservabilityScopeResolution:
    role: str
    org_id: UUID | None
    dept_id: UUID | None
    allowed_user_ids: set[str]
    bindings: list[LangfuseBinding]


async def _user_org_ids(session: AsyncSession, user_id: UUID) -> set[UUID]:
    rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
        )
    ).all()
    return {row for row in rows}


async def _user_dept_rows(session: AsyncSession, user_id: UUID) -> list[tuple[UUID, UUID]]:
    rows = (
        await session.exec(
            select(UserDepartmentMembership.department_id, UserDepartmentMembership.org_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
            )
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def _resolve_department(session: AsyncSession, dept_id: UUID) -> Department:
    department = await session.get(Department, dept_id)
    if not department:
        raise ObservabilityScopeError("Department not found.")
    return department


async def _users_for_departments(
    session: AsyncSession,
    *,
    dept_ids: set[UUID],
    role_names: set[str],
) -> set[str]:
    if not dept_ids:
        return set()
    rows = (
        await session.exec(
            select(distinct(User.id))
            .join(UserDepartmentMembership, UserDepartmentMembership.user_id == User.id)
            .where(
                UserDepartmentMembership.department_id.in_(list(dept_ids)),
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                User.role.in_(list(role_names)),
            )
        )
    ).all()
    return {str(row) for row in rows}


async def _users_for_organizations(
    session: AsyncSession,
    *,
    org_ids: set[UUID],
    role_names: set[str],
) -> set[str]:
    if not org_ids:
        return set()
    rows = (
        await session.exec(
            select(distinct(User.id))
            .join(UserOrganizationMembership, UserOrganizationMembership.user_id == User.id)
            .where(
                UserOrganizationMembership.org_id.in_(list(org_ids)),
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                User.role.in_(list(role_names)),
            )
        )
    ).all()
    return {str(row) for row in rows}


async def _active_department_bindings(
    session: AsyncSession,
    dept_ids: set[UUID],
) -> list[LangfuseBinding]:
    if not dept_ids:
        return []
    rows = (
        await session.exec(
            select(LangfuseBinding).where(
                LangfuseBinding.is_active.is_(True),
                LangfuseBinding.scope_type == "department",
                LangfuseBinding.dept_id.in_(list(dept_ids)),
            )
        )
    ).all()
    return list(rows)


async def _active_org_admin_bindings(
    session: AsyncSession,
    org_ids: set[UUID],
) -> list[LangfuseBinding]:
    if not org_ids:
        return []
    rows = (
        await session.exec(
            select(LangfuseBinding).where(
                LangfuseBinding.is_active.is_(True),
                LangfuseBinding.scope_type == "org_admin",
                LangfuseBinding.org_id.in_(list(org_ids)),
                LangfuseBinding.dept_id.is_(None),
            )
        )
    ).all()
    return list(rows)


def _dedupe_bindings(bindings: list[LangfuseBinding]) -> list[LangfuseBinding]:
    seen: set[UUID] = set()
    deduped: list[LangfuseBinding] = []
    for binding in bindings:
        if binding.id in seen:
            continue
        seen.add(binding.id)
        deduped.append(binding)
    return deduped


async def resolve_observability_scope(
    session: AsyncSession,
    *,
    current_user: User,
    org_id: UUID | None = None,
    dept_id: UUID | None = None,
    enforce_filter_for_admin: bool = True,
    trace_scope: str = "all",
) -> ObservabilityScopeResolution:
    role = normalize_role(current_user.role)
    user_id = current_user.id
    org_ids = await _user_org_ids(session, user_id)
    dept_rows = await _user_dept_rows(session, user_id)
    dept_ids = {dept for dept, _ in dept_rows}
    dept_to_org = {dept: org for dept, org in dept_rows}

    selected_org_id = org_id
    selected_dept_id = dept_id
    selected_department: Department | None = None

    if selected_dept_id is not None:
        selected_department = await _resolve_department(session, selected_dept_id)
        if selected_org_id is None:
            selected_org_id = selected_department.org_id

    allowed_user_ids: set[str] = {str(user_id)}
    target_dept_ids: set[UUID] = set()
    target_org_ids: set[UUID] = set()

    if role in {"business_user", "developer", "consumer"}:
        target_dept_ids = dept_ids
        if selected_dept_id and selected_dept_id in dept_ids:
            target_dept_ids = {selected_dept_id}
        target_org_ids = {dept_to_org[d] for d in target_dept_ids if d in dept_to_org}

    elif role == "department_admin":
        if not dept_ids:
            raise ObservabilityScopeError("Department admin has no active department membership.")
        if selected_dept_id is not None and selected_dept_id not in dept_ids:
            raise ObservabilityScopeError("Selected department is outside your scope.")
        target_dept_ids = {selected_dept_id} if selected_dept_id else dept_ids
        target_org_ids = {dept_to_org[d] for d in target_dept_ids if d in dept_to_org}
        if trace_scope != "my":
            allowed_user_ids |= await _users_for_departments(
                session,
                dept_ids=target_dept_ids,
                role_names=DEPT_ADMIN_VISIBLE_ROLES,
            )

    elif role == "super_admin":
        if not org_ids:
            raise ObservabilityScopeError("Super admin has no active organization scope.")
        if selected_org_id is not None and selected_org_id not in org_ids:
            raise ObservabilityScopeError("Selected organization is outside your scope.")
        if selected_department and selected_department.org_id not in org_ids:
            raise ObservabilityScopeError("Selected department is outside your organization scope.")

        # trace_scope="all" → org-wide (all projects), no filter required
        # trace_scope="dept" → specific department, dept_id required
        # trace_scope="my" → only own traces, no filter required
        if trace_scope == "dept":
            if enforce_filter_for_admin and selected_dept_id is None:
                raise ObservabilityScopeError("dept_id is required for department trace scope.")
        elif enforce_filter_for_admin and selected_org_id is None and selected_dept_id is None:
            # "all" and "my" auto-resolve to the super_admin's org(s)
            pass

        if trace_scope == "dept" and selected_department:
            # Narrow to the single selected department only
            target_dept_ids = {selected_department.id}
            target_org_ids = {selected_department.org_id}
            allowed_user_ids |= await _users_for_departments(
                session,
                dept_ids=target_dept_ids,
                role_names=SUPER_ADMIN_VISIBLE_ROLES,
            )
        else:
            # "all" and "my" — org-wide resolution
            target_org_ids = {selected_org_id} if selected_org_id else set(org_ids)
            dept_in_scope_rows = (
                await session.exec(
                    select(Department.id).where(
                        Department.org_id.in_(list(target_org_ids)),
                        Department.status == "active",
                    )
                )
            ).all()
            target_dept_ids = {row for row in dept_in_scope_rows}
            if trace_scope != "my":
                allowed_user_ids |= await _users_for_organizations(
                    session,
                    org_ids=target_org_ids,
                    role_names=SUPER_ADMIN_VISIBLE_ROLES,
                )

    elif role in {"root", "leader_executive"}:
        if enforce_filter_for_admin and selected_org_id is None and selected_dept_id is None:
            raise ObservabilityScopeError("org_id or dept_id is required for root observability.")
        if selected_department:
            target_dept_ids = {selected_department.id}
            target_org_ids = {selected_department.org_id}
            allowed_user_ids |= await _users_for_departments(
                session,
                dept_ids=target_dept_ids,
                role_names=DEPT_ADMIN_VISIBLE_ROLES | {"department_admin"},
            )
            allowed_user_ids |= await _users_for_organizations(
                session,
                org_ids=target_org_ids,
                role_names={"super_admin"},
            )
        else:
            if selected_org_id is not None:
                target_org_ids = {selected_org_id}
            else:
                all_org_rows = (await session.exec(select(Organization.id))).all()
                target_org_ids = {row for row in all_org_rows if row is not None}
            dept_in_scope_rows = (
                await session.exec(
                    select(Department.id).where(
                        Department.org_id.in_(list(target_org_ids)),
                        Department.status == "active",
                    )
                )
            ).all()
            target_dept_ids = {row for row in dept_in_scope_rows}
            allowed_user_ids |= await _users_for_organizations(
                session,
                org_ids=target_org_ids,
                role_names=ROOT_VISIBLE_ROLES,
            )
    else:
        target_dept_ids = dept_ids
        target_org_ids = {dept_to_org[d] for d in target_dept_ids if d in dept_to_org}

    bindings: list[LangfuseBinding] = []
    if target_dept_ids:
        bindings.extend(await _active_department_bindings(session, target_dept_ids))
    if role in {"root", "super_admin", "leader_executive"} and target_org_ids and trace_scope != "dept":
        bindings.extend(await _active_org_admin_bindings(session, target_org_ids))

    return ObservabilityScopeResolution(
        role=role,
        org_id=selected_org_id,
        dept_id=selected_dept_id,
        allowed_user_ids=allowed_user_ids,
        bindings=_dedupe_bindings(bindings),
    )


async def resolve_write_langfuse_binding(
    session: AsyncSession,
    *,
    user_id: UUID,
    agent_id: UUID | None = None,
    selected_dept_id: UUID | None = None,
) -> LangfuseBinding | None:
    user = await session.get(User, user_id)
    if not user:
        return None

    role = normalize_role(user.role)
    org_ids = await _user_org_ids(session, user_id)
    dept_rows = await _user_dept_rows(session, user_id)
    dept_ids = {dept for dept, _ in dept_rows}

    candidate_org_id: UUID | None = None
    candidate_dept_id: UUID | None = None

    if agent_id is not None:
        agent = await session.get(Agent, agent_id)
        if agent:
            candidate_org_id = agent.org_id
            candidate_dept_id = agent.dept_id

    if candidate_dept_id is None and selected_dept_id is not None:
        candidate_dept_id = selected_dept_id

    if candidate_dept_id is None and dept_rows:
        candidate_dept_id = sorted((row[0] for row in dept_rows), key=str)[0]

    if candidate_dept_id is not None and candidate_org_id is None:
        department = await session.get(Department, candidate_dept_id)
        if department:
            candidate_org_id = department.org_id

    if candidate_dept_id is not None:
        can_use_dept = False
        if role == "root":
            can_use_dept = True
        elif role == "super_admin":
            if candidate_org_id and candidate_org_id in org_ids:
                can_use_dept = True
        else:
            can_use_dept = candidate_dept_id in dept_ids

        if can_use_dept:
            dept_binding = (
                await session.exec(
                    select(LangfuseBinding).where(
                        LangfuseBinding.is_active.is_(True),
                        LangfuseBinding.scope_type == "department",
                        LangfuseBinding.dept_id == candidate_dept_id,
                    )
                )
            ).first()
            if dept_binding:
                return dept_binding

    if role in {"root", "super_admin"}:
        if candidate_org_id is None and org_ids:
            candidate_org_id = sorted(org_ids, key=str)[0]
        if candidate_org_id is None:
            return None
        if role == "super_admin" and candidate_org_id not in org_ids:
            return None
        return (
            await session.exec(
                select(LangfuseBinding).where(
                    LangfuseBinding.is_active.is_(True),
                    LangfuseBinding.scope_type == "org_admin",
                    LangfuseBinding.org_id == candidate_org_id,
                    LangfuseBinding.dept_id.is_(None),
                )
            )
        ).first()

    return None
