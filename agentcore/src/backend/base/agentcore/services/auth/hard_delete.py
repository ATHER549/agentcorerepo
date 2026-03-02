from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, distinct, update
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.auth.invalidation import invalidate_user_auth
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership


async def _delete_org_scoped_rows(db: AsyncSession, org_id: UUID) -> None:
    org_tables = [table for table in SQLModel.metadata.sorted_tables if "org_id" in table.c]
    for table in reversed(org_tables):
        if table.name == "organization":
            continue
        await db.exec(delete(table).where(table.c.org_id == org_id))


async def _delete_department_scoped_rows(db: AsyncSession, department_id: UUID) -> None:
    dept_tables = [table for table in SQLModel.metadata.sorted_tables if "department_id" in table.c]
    for table in reversed(dept_tables):
        if table.name == "department":
            continue
        await db.exec(delete(table).where(table.c.department_id == department_id))


async def hard_delete_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    delete_owned_organizations: bool = True,
) -> None:
    user = await db.get(User, user_id)
    if not user:
        return

    await invalidate_user_auth(
        user_id,
        email=user.email or user.username,
        entra_object_id=user.entra_object_id,
    )

    if delete_owned_organizations:
        owned_org_ids = (
            await db.exec(select(Organization.id).where(Organization.owner_user_id == user_id))
        ).all()
        for org_id in owned_org_ids:
            await hard_delete_organization(
                db,
                org_id,
                delete_member_users=True,
                skip_user_ids={user_id},
            )

    administered_department_ids = (
        await db.exec(select(Department.id).where(Department.admin_user_id == user_id))
    ).all()
    for department_id in administered_department_ids:
        await hard_delete_department(
            db,
            department_id,
            delete_member_users=True,
            skip_user_ids={user_id},
        )

    for table in reversed(SQLModel.metadata.sorted_tables):
        if table.name == "user":
            continue

        user_fk_columns = [
            col
            for col in table.c
            if any(fk.column.table.name == "user" and fk.column.name == "id" for fk in col.foreign_keys)
        ]
        for col in user_fk_columns:
            if col.nullable:
                await db.exec(update(table).where(col == user_id).values({col.name: None}))
            else:
                await db.exec(delete(table).where(col == user_id))

    await db.exec(delete(User).where(User.id == user_id))


async def hard_delete_organization(
    db: AsyncSession,
    org_id: UUID,
    *,
    delete_member_users: bool = True,
    skip_user_ids: set[UUID] | None = None,
) -> None:
    org = await db.get(Organization, org_id)
    if not org:
        return

    skip_ids = skip_user_ids or set()

    member_user_ids = (
        await db.exec(
            select(distinct(UserOrganizationMembership.user_id)).where(
                UserOrganizationMembership.org_id == org_id,
            )
        )
    ).all()

    for member_user_id in member_user_ids:
        if member_user_id in skip_ids:
            continue
        member_user = await db.get(User, member_user_id)
        if member_user:
            await invalidate_user_auth(
                member_user_id,
                email=member_user.email or member_user.username,
                entra_object_id=member_user.entra_object_id,
            )
        else:
            await invalidate_user_auth(member_user_id)

    if delete_member_users and member_user_ids:
        member_rows = (
            await db.exec(select(User.id, User.role).where(User.id.in_(list(member_user_ids))))
        ).all()
        for member_user_id, member_role in member_rows:
            if member_user_id in skip_ids:
                continue
            if normalize_role(member_role) == "root":
                continue
            await hard_delete_user(
                db,
                member_user_id,
                delete_owned_organizations=False,
            )

    await _delete_org_scoped_rows(db, org_id)
    await db.exec(delete(Organization).where(Organization.id == org_id))


async def hard_delete_department(
    db: AsyncSession,
    department_id: UUID,
    *,
    delete_member_users: bool = True,
    skip_user_ids: set[UUID] | None = None,
) -> None:
    department = await db.get(Department, department_id)
    if not department:
        return

    skip_ids = skip_user_ids or set()

    member_user_ids = (
        await db.exec(
            select(distinct(UserDepartmentMembership.user_id)).where(
                UserDepartmentMembership.department_id == department_id,
            )
        )
    ).all()

    if delete_member_users and member_user_ids:
        member_rows = (
            await db.exec(select(User.id, User.role).where(User.id.in_(list(member_user_ids))))
        ).all()
        for member_user_id, member_role in member_rows:
            if member_user_id in skip_ids:
                continue
            normalized_role = normalize_role(member_role)
            if normalized_role in {"root", "super_admin"}:
                continue
            await hard_delete_user(
                db,
                member_user_id,
                delete_owned_organizations=False,
            )

    await _delete_department_scoped_rows(db, department_id)
    await db.exec(delete(Department).where(Department.id == department_id))
