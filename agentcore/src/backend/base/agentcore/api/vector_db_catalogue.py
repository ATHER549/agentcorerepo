from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_, tuple_
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.database.models.vector_db_catalogue.model import VectorDBCatalogue

router = APIRouter(prefix="/vector-db-catalogue", tags=["Vector DB Catalogue"])


class VectorDBPayload(BaseModel):
    name: str
    description: str | None = None
    provider: str
    deployment: str
    dimensions: str
    indexType: str
    status: str = "connected"
    vectorCount: str = "0"
    isCustom: bool = False
    org_id: UUID | None = None
    dept_id: UUID | None = None


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    return str(getattr(current_user, "role", "")).lower() == "root"


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


async def _visibility_filters(session: DbSession, current_user: CurrentActiveUser):
    if _is_root_user(current_user):
        return []

    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    filters = [and_(VectorDBCatalogue.org_id.is_(None), VectorDBCatalogue.dept_id.is_(None))]

    if org_ids:
        filters.append(and_(VectorDBCatalogue.org_id.in_(list(org_ids)), VectorDBCatalogue.dept_id.is_(None)))

    if dept_pairs:
        filters.append(tuple_(VectorDBCatalogue.org_id, VectorDBCatalogue.dept_id).in_(dept_pairs))

    return filters


async def _validate_scope_refs(session: DbSession, payload: VectorDBPayload) -> None:
    if payload.dept_id and not payload.org_id:
        raise HTTPException(status_code=400, detail="dept_id requires org_id")

    if payload.org_id:
        org = await session.get(Organization, payload.org_id)
        if not org:
            raise HTTPException(status_code=400, detail="Invalid org_id")

    if payload.dept_id:
        dept = (
            await session.exec(
                select(Department).where(
                    Department.id == payload.dept_id,
                    Department.org_id == payload.org_id,
                )
            )
        ).first()
        if not dept:
            raise HTTPException(status_code=400, detail="Invalid dept_id for org_id")


def _serialize_vector_db(row: VectorDBCatalogue) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "provider": row.provider,
        "deployment": row.deployment,
        "dimensions": row.dimensions,
        "indexType": row.index_type,
        "status": row.status,
        "vectorCount": row.vector_count,
        "isCustom": bool(row.is_custom),
        "org_id": str(row.org_id) if row.org_id else None,
        "dept_id": str(row.dept_id) if row.dept_id else None,
    }


@router.get("")
@router.get("/")
async def list_vector_db_catalogue(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict]:
    filters = await _visibility_filters(session, current_user)
    query = select(VectorDBCatalogue).order_by(VectorDBCatalogue.name.asc())
    if filters:
        query = query.where(or_(*filters))

    rows = (await session.exec(query)).all()
    return [_serialize_vector_db(row) for row in rows]


@router.post("")
@router.post("/")
async def create_vector_db_catalogue(
    payload: VectorDBPayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    await _validate_scope_refs(session, payload)
    now = datetime.now(timezone.utc)
    row = VectorDBCatalogue(
        name=payload.name,
        description=payload.description,
        provider=payload.provider,
        deployment=payload.deployment,
        dimensions=payload.dimensions,
        index_type=payload.indexType,
        status=payload.status,
        vector_count=payload.vectorCount,
        is_custom=payload.isCustom,
        org_id=payload.org_id,
        dept_id=payload.dept_id,
        created_by=current_user.id,
        updated_by=current_user.id,
        created_at=now,
        updated_at=now,
        published_by=current_user.id if payload.status == "connected" else None,
        published_at=now if payload.status == "connected" else None,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize_vector_db(row)


@router.patch("/{vector_db_id}")
async def update_vector_db_catalogue(
    vector_db_id: UUID,
    payload: VectorDBPayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    row = await session.get(VectorDBCatalogue, vector_db_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vector DB entry not found")

    await _validate_scope_refs(session, payload)
    now = datetime.now(timezone.utc)

    row.name = payload.name
    row.description = payload.description
    row.provider = payload.provider
    row.deployment = payload.deployment
    row.dimensions = payload.dimensions
    row.index_type = payload.indexType
    row.status = payload.status
    row.vector_count = payload.vectorCount
    row.is_custom = payload.isCustom
    row.org_id = payload.org_id
    row.dept_id = payload.dept_id
    row.updated_by = current_user.id
    row.updated_at = now
    if payload.status == "connected":
        row.published_by = current_user.id
        row.published_at = now

    await session.commit()
    await session.refresh(row)
    return _serialize_vector_db(row)


@router.delete("/{vector_db_id}")
async def delete_vector_db_catalogue(
    vector_db_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    row = await session.get(VectorDBCatalogue, vector_db_id)
    if not row:
        raise HTTPException(status_code=404, detail="Vector DB entry not found")

    await session.delete(row)
    await session.commit()
    return {"message": "Vector DB entry deleted successfully"}
