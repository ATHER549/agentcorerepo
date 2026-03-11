from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from agentcore.api.utils import DbSession
from agentcore.services.auth.decorators import PermissionChecker
from agentcore.services.auth.hard_delete import hard_delete_organization
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User

router = APIRouter(tags=["Organizations"], prefix="/organizations")


@router.delete("/{org_id}")
async def delete_organization(
    org_id: UUID,
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> dict:
    if normalize_role(current_user.role) != "root":
        raise HTTPException(status_code=403, detail="Only root can delete organizations.")

    org = (await session.exec(select(Organization).where(Organization.id == org_id))).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        await hard_delete_organization(
            session,
            org_id,
            delete_member_users=True,
            skip_user_ids={current_user.id},
        )
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Could not hard delete organization due to database constraints.",
        ) from e

    return {"detail": "Organization deleted"}

