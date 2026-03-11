from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from agentcore.api.utils import DbSession
from agentcore.services.auth.decorators import PermissionChecker
from agentcore.services.auth.hard_delete import hard_delete_department
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership

router = APIRouter(tags=["Departments"], prefix="/departments")
ACTIVE_ORG_STATUSES = {"accepted", "active"}


@router.delete("/{department_id}")
async def delete_department(
    department_id: UUID,
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> dict:
    current_role = normalize_role(current_user.role)
    if current_role not in {"root", "super_admin"}:
        raise HTTPException(status_code=403, detail="Only root or super admin can delete departments.")

    department = (await session.exec(select(Department).where(Department.id == department_id))).first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    if current_role == "super_admin":
        allowed_org_ids = (
            await session.exec(
                select(UserOrganizationMembership.org_id).where(
                    UserOrganizationMembership.user_id == current_user.id,
                    UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                )
            )
        ).all()
        if department.org_id not in set(allowed_org_ids):
            raise HTTPException(status_code=403, detail="Permission denied")

    try:
        await hard_delete_department(
            session,
            department_id,
            delete_member_users=True,
            skip_user_ids={current_user.id},
        )
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Could not hard delete department due to database constraints.",
        ) from e

    return {"detail": "Department deleted"}
