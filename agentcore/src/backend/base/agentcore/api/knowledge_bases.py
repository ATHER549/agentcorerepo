from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlmodel import select as sm_select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.file.model import File as UserFile
from agentcore.services.database.models.knowledge_base.model import KBVisibilityEnum, KnowledgeBase
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.deps import get_storage_service
from agentcore.services.storage.service import StorageService

router = APIRouter(tags=["Knowledge Bases"], prefix="/knowledge_bases")


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_admin_role(role: str | None) -> bool:
    return normalize_role(role or "") in {"super_admin", "department_admin", "root"}


async def _get_scope_memberships(session: DbSession, user_id: UUID) -> tuple[set[UUID], set[UUID]]:
    org_rows = (
        await session.exec(
            sm_select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.status.in_(["accepted", "active"]),
            )
        )
    ).all()
    dept_rows = (
        await session.exec(
            sm_select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    org_ids = {r if isinstance(r, UUID) else r[0] for r in org_rows}
    dept_ids = {r if isinstance(r, UUID) else r[0] for r in dept_rows}
    return org_ids, dept_ids


def _knowledge_base_visibility_predicate(current_user: CurrentActiveUser):
    """DB-enforced visibility predicate:
    - PRIVATE: owner + department.admin_user_id for creator's active department(s)
    - DEPARTMENT: viewer and creator share at least one active department
    - ORGANIZATION: viewer and creator share at least one active organization
    """
    viewer_dept_ids = select(UserDepartmentMembership.department_id).where(
        UserDepartmentMembership.user_id == current_user.id,
        UserDepartmentMembership.status == "active",
    )
    creator_shares_department = (
        select(UserDepartmentMembership.id)
        .where(
            UserDepartmentMembership.user_id == KnowledgeBase.created_by,
            UserDepartmentMembership.status == "active",
            UserDepartmentMembership.department_id.in_(viewer_dept_ids),
        )
        .exists()
    )
    viewer_org_ids = select(UserOrganizationMembership.org_id).where(
        UserOrganizationMembership.user_id == current_user.id,
        UserOrganizationMembership.status.in_(["accepted", "active"]),
    )
    creator_shares_organization = (
        select(UserOrganizationMembership.id)
        .where(
            UserOrganizationMembership.user_id == KnowledgeBase.created_by,
            UserOrganizationMembership.status.in_(["accepted", "active"]),
            UserOrganizationMembership.org_id.in_(viewer_org_ids),
        )
        .exists()
    )
    viewer_is_dept_admin_of_creator_dept = (
        select(Department.id)
        .where(
            Department.admin_user_id == current_user.id,
            Department.id.in_(
                select(UserDepartmentMembership.department_id).where(
                    UserDepartmentMembership.user_id == KnowledgeBase.created_by,
                    UserDepartmentMembership.status == "active",
                )
            ),
        )
        .exists()
    )
    return or_(
        KnowledgeBase.created_by == current_user.id,
        and_(
            KnowledgeBase.visibility == KBVisibilityEnum.PRIVATE,
            viewer_is_dept_admin_of_creator_dept,
        ),
        and_(
            KnowledgeBase.visibility == KBVisibilityEnum.DEPARTMENT,
            creator_shares_department,
        ),
        and_(
            KnowledgeBase.visibility == KBVisibilityEnum.ORGANIZATION,
            creator_shares_organization,
        ),
    )


async def _can_manage_knowledge_base(
    session: DbSession,
    current_user: CurrentActiveUser,
    kb: KnowledgeBase,
) -> bool:
    if kb.created_by == current_user.id:
        return True

    stmt = sm_select(KnowledgeBase.id).where(
        KnowledgeBase.id == kb.id,
        _knowledge_base_visibility_predicate(current_user),
    )
    return (await session.exec(stmt)).first() is not None


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


async def _enforce_kb_scope_for_update(
    session: DbSession,
    current_user: CurrentActiveUser,
    kb: KnowledgeBase,
    visibility: KBVisibilityEnum,
    public_scope: str | None,
    org_id: UUID | None,
    dept_id: UUID | None,
) -> tuple[KBVisibilityEnum, UUID | None, UUID | None]:
    org_ids, _ = await _get_scope_memberships(session, current_user.id)
    dept_rows = (
        await session.exec(
            sm_select(UserDepartmentMembership.org_id, UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.status == "active",
            )
        )
    ).all()
    dept_pairs = [(row[0], row[1]) for row in dept_rows]

    target_visibility = visibility
    target_org_id = org_id if org_id is not None else kb.org_id
    target_dept_id = dept_id if dept_id is not None else kb.dept_id

    if target_visibility == KBVisibilityEnum.PRIVATE:
        return KBVisibilityEnum.PRIVATE, kb.org_id, kb.dept_id

    if target_visibility == KBVisibilityEnum.ORGANIZATION:
        if not target_org_id:
            if not org_ids:
                raise HTTPException(status_code=403, detail="No active organization scope found")
            target_org_id = sorted(org_ids, key=str)[0]
        if target_org_id not in org_ids:
            raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
        target_dept_id = None
        await _validate_scope_refs(session, target_org_id, target_dept_id)
        return target_visibility, target_org_id, target_dept_id

    if target_visibility == KBVisibilityEnum.DEPARTMENT:
        if not dept_pairs:
            raise HTTPException(status_code=403, detail="No active department scope found")
        allowed_pairs = {(org, dept) for org, dept in dept_pairs}
        if target_org_id and target_dept_id:
            if (target_org_id, target_dept_id) not in allowed_pairs:
                raise HTTPException(status_code=403, detail="dept_id must belong to your department scope")
            await _validate_scope_refs(session, target_org_id, target_dept_id)
            return target_visibility, target_org_id, target_dept_id
        current_org_id, current_dept_id = sorted(allowed_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
        await _validate_scope_refs(session, current_org_id, current_dept_id)
        return target_visibility, current_org_id, current_dept_id

    if target_visibility.value == "PUBLIC":
        if not public_scope:
            raise HTTPException(status_code=400, detail="public_scope is required when visibility is public")
        normalized_public_scope = public_scope.strip().lower()
        if normalized_public_scope == "organization":
            return await _enforce_kb_scope_for_update(
                session,
                current_user,
                kb,
                KBVisibilityEnum.ORGANIZATION,
                public_scope,
                target_org_id,
                target_dept_id,
            )
        if normalized_public_scope == "department":
            return await _enforce_kb_scope_for_update(
                session,
                current_user,
                kb,
                KBVisibilityEnum.DEPARTMENT,
                public_scope,
                target_org_id,
                target_dept_id,
            )
        raise HTTPException(status_code=400, detail="Unsupported public_scope")

    return target_visibility, target_org_id, target_dept_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", status_code=HTTPStatus.OK)
@router.get("/", status_code=HTTPStatus.OK)
async def list_knowledge_bases(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict]:
    viewer_org_ids, viewer_dept_ids = await _get_scope_memberships(session, current_user.id)
    visibility_predicate = _knowledge_base_visibility_predicate(current_user)
    stmt = (
        select(
            KnowledgeBase.id,
            KnowledgeBase.name,
            KnowledgeBase.visibility,
            KnowledgeBase.org_id,
            KnowledgeBase.dept_id,
            KnowledgeBase.created_by,
            KnowledgeBase.updated_at.label("kb_updated_at"),
            func.max(UserFile.updated_at).label("last_file_updated_at"),
            func.coalesce(func.sum(UserFile.size), 0).label("size"),
            func.count(UserFile.id).label("file_count"),
        )
        .select_from(KnowledgeBase)
        .join(UserFile, UserFile.knowledge_base_id == KnowledgeBase.id, isouter=True)
        .where(visibility_predicate)
        .group_by(
            KnowledgeBase.id,
            KnowledgeBase.name,
            KnowledgeBase.visibility,
            KnowledgeBase.org_id,
            KnowledgeBase.dept_id,
            KnowledgeBase.created_by,
            KnowledgeBase.updated_at,
        )
        .order_by(KnowledgeBase.name.asc())
    )
    rows = (await session.exec(stmt)).all()

    payload: list[dict] = []
    role = normalize_role(getattr(current_user, "role", None) or "")
    creator_ids = {row.created_by for row in rows if row.created_by}
    creator_email_map: dict[UUID, str] = {}
    dept_map: dict[UUID, str] = {}
    org_map: dict[UUID, str] = {}
    creator_dept_ids_map: dict[UUID, set[UUID]] = {}
    creator_org_ids_map: dict[UUID, set[UUID]] = {}

    if creator_ids:
        creator_rows = (
            await session.exec(select(User.id, User.email, User.username).where(User.id.in_(list(creator_ids))))
        ).all()
        creator_email_map = {uid: (email or username) for uid, email, username in creator_rows}

        creator_dept_rows = (
            await session.exec(
                select(UserDepartmentMembership.user_id, UserDepartmentMembership.department_id).where(
                    UserDepartmentMembership.user_id.in_(list(creator_ids)),
                    UserDepartmentMembership.status == "active",
                )
            )
        ).all()
        for user_id, dept_id in creator_dept_rows:
            creator_dept_ids_map.setdefault(user_id, set()).add(dept_id)

        creator_org_rows = (
            await session.exec(
                select(UserOrganizationMembership.user_id, UserOrganizationMembership.org_id).where(
                    UserOrganizationMembership.user_id.in_(list(creator_ids)),
                    UserOrganizationMembership.status.in_(["accepted", "active"]),
                )
            )
        ).all()
        for user_id, org_id in creator_org_rows:
            creator_org_ids_map.setdefault(user_id, set()).add(org_id)

        if role in {"department_admin", "super_admin", "root"}:
            dept_rows = (
                await session.exec(
                    select(UserDepartmentMembership.user_id, Department.name)
                    .join(Department, Department.id == UserDepartmentMembership.department_id)
                    .where(
                        UserDepartmentMembership.user_id.in_(list(creator_ids)),
                        UserDepartmentMembership.status == "active",
                    )
                )
            ).all()
            for user_id, dept_name in dept_rows:
                dept_map.setdefault(user_id, dept_name)

        if role == "root":
            org_rows = (
                await session.exec(
                    select(UserOrganizationMembership.user_id, Organization.name)
                    .join(Organization, Organization.id == UserOrganizationMembership.org_id)
                    .where(
                        UserOrganizationMembership.user_id.in_(list(creator_ids)),
                        UserOrganizationMembership.status.in_(["accepted", "active"]),
                    )
                )
            ).all()
            for user_id, org_name in org_rows:
                org_map.setdefault(user_id, org_name)

    for row in rows:
        creator_dept_ids = creator_dept_ids_map.get(row.created_by, set())
        creator_org_ids = creator_org_ids_map.get(row.created_by, set())
        viewer_is_dept_admin_of_creator = (
            await session.exec(
                select(Department.id).where(
                    Department.admin_user_id == current_user.id,
                    Department.id.in_(list(creator_dept_ids)),
                )
            )
        ).first() is not None
        visible_by_scope = (
            row.created_by == current_user.id
            or (
                row.visibility == KBVisibilityEnum.PRIVATE
                and viewer_is_dept_admin_of_creator
            )
            or (
                row.visibility == KBVisibilityEnum.DEPARTMENT
                and bool(creator_dept_ids.intersection(viewer_dept_ids))
            )
            or (
                row.visibility == KBVisibilityEnum.ORGANIZATION
                and bool(creator_org_ids.intersection(viewer_org_ids))
            )
        )
        if not visible_by_scope:
            continue

        timestamps = [_to_utc(ts) for ts in (row.kb_updated_at, row.last_file_updated_at)]
        timestamps = [ts for ts in timestamps if ts is not None]
        last_activity = max(timestamps) if timestamps else None
        is_own = row.created_by == current_user.id
        created_by_email = creator_email_map.get(row.created_by)
        department_name = dept_map.get(row.created_by)
        organization_name = org_map.get(row.created_by)

        if role in {"developer", "business_user"}:
            created_by_email = None
            department_name = None
            organization_name = None
        elif role == "department_admin":
            department_name = None
            organization_name = None
        elif role == "super_admin":
            organization_name = None
        elif role == "root" and is_own:
            department_name = None
            organization_name = None

        payload.append(
            {
                "id": str(row.id),
                "name": row.name,
                "visibility": row.visibility.value if row.visibility else "PRIVATE",
                "org_id": str(row.org_id) if row.org_id else None,
                "dept_id": str(row.dept_id) if row.dept_id else None,
                "created_by": str(row.created_by),
                "size": int(row.size or 0),
                "words": 0,
                "characters": 0,
                "chunks": 0,
                "avg_chunk_size": 0,
                "file_count": int(row.file_count or 0),
                "updated_at": row.kb_updated_at.isoformat() if row.kb_updated_at else None,
                "last_activity": last_activity.isoformat() if last_activity else None,
                "is_own_kb": is_own,
                "created_by_email": created_by_email,
                "department_name": department_name,
                "organization_name": organization_name,
            }
        )

    return payload


@router.get("/visibility-options", status_code=HTTPStatus.OK)
async def get_knowledge_base_visibility_options(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    org_ids, dept_ids = await _get_scope_memberships(session, current_user.id)
    role = normalize_role(getattr(current_user, "role", None) or "")

    organizations = []
    if role == "root":
        org_rows = (await session.exec(select(Organization.id, Organization.name))).all()
        organizations = [{"id": str(r[0]), "name": r[1]} for r in org_rows]
    elif org_ids:
        org_rows = (
            await session.exec(select(Organization.id, Organization.name).where(Organization.id.in_(list(org_ids))))
        ).all()
        organizations = [{"id": str(r[0]), "name": r[1]} for r in org_rows]

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

    return {
        "organizations": organizations,
        "departments": departments,
        "role": role,
    }


class KnowledgeBaseUpdate(BaseModel):
    visibility: KBVisibilityEnum
    public_scope: str | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None


@router.patch("/{kb_id}", status_code=HTTPStatus.OK)
async def update_knowledge_base(
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
    current_user: CurrentActiveUser,
    session: DbSession,
):
    """Update KB visibility. Only the creator or admins can change visibility."""
    kb = (
        await session.exec(
            sm_select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
    ).first()

    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if not await _can_manage_knowledge_base(session, current_user, kb):
        raise HTTPException(status_code=403, detail="Not authorized to update this knowledge base")

    visibility, org_id, dept_id = await _enforce_kb_scope_for_update(
        session=session,
        current_user=current_user,
        kb=kb,
        visibility=payload.visibility,
        public_scope=payload.public_scope,
        org_id=payload.org_id,
        dept_id=payload.dept_id,
    )

    kb.visibility = visibility
    kb.org_id = org_id
    kb.dept_id = dept_id
    kb.updated_at = datetime.now(timezone.utc)

    session.add(kb)
    await session.commit()
    await session.refresh(kb)

    return {
        "id": str(kb.id),
        "name": kb.name,
        "visibility": kb.visibility.value,
        "org_id": str(kb.org_id) if kb.org_id else None,
        "dept_id": str(kb.dept_id) if kb.dept_id else None,
        "updated_at": kb.updated_at.isoformat(),
    }


@router.delete("/{kb_id}", status_code=HTTPStatus.OK)
async def delete_knowledge_base(
    kb_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: StorageService = Depends(get_storage_service),
):
    kb = (
        await session.exec(
            sm_select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
            )
        )
    ).first()

    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if not await _can_manage_knowledge_base(session, current_user, kb):
        raise HTTPException(status_code=403, detail="Not authorized to delete this knowledge base")

    files = (await session.exec(sm_select(UserFile).where(UserFile.knowledge_base_id == kb.id))).all()
    for file in files:
        try:
            storage_path = file.path
            user_prefix = f"{file.user_id}/"
            if storage_path.startswith(user_prefix):
                storage_path = storage_path[len(user_prefix):]
            await storage_service.delete_file(agent_id=str(file.user_id), file_name=storage_path)
        except Exception:
            pass
        await session.delete(file)

    await session.delete(kb)
    await session.commit()
    return {"message": "Knowledge base deleted successfully"}


@router.delete("", status_code=HTTPStatus.OK)
@router.delete("/", status_code=HTTPStatus.OK)
async def delete_knowledge_bases_batch(
    payload: dict,
    current_user: CurrentActiveUser,
    session: DbSession,
    storage_service: StorageService = Depends(get_storage_service),
):
    kb_ids = payload.get("kb_names", [])
    if not isinstance(kb_ids, list) or not kb_ids:
        raise HTTPException(status_code=400, detail="kb_names must be a non-empty list")

    deleted_count = 0
    for raw_id in kb_ids:
        try:
            kb_id = UUID(str(raw_id))
        except Exception:
            continue
        try:
            await delete_knowledge_base(kb_id, current_user, session, storage_service)
            deleted_count += 1
        except HTTPException:
            continue

    return {"deleted_count": deleted_count, "timestamp": datetime.now(timezone.utc).isoformat()}
