from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from agentcore.api.utils import DbSession
from agentcore.services.auth.decorators import PermissionChecker
from agentcore.services.auth.permissions import normalize_role
from agentcore.services.auth.utils import get_current_active_user
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.langfuse_binding.model import LangfuseBinding
from agentcore.services.database.models.observability_provision_job.model import ObservabilityProvisionJob
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.observability import (
    LangfuseProvisioningError,
    get_langfuse_provisioning_service,
)


router = APIRouter(
    prefix="/observability",
    tags=["Observability Provisioning"],
    dependencies=[Depends(PermissionChecker(["view_observability_page"]))],
)

ACTIVE_ORG_STATUSES = {"accepted", "active"}
ACTIVE_DEPT_STATUS = "active"


class ProvisionJobRead(BaseModel):
    id: UUID
    idempotency_key: str
    scope_type: str
    org_id: UUID | None = None
    dept_id: UUID | None = None
    status: str
    retry_count: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class BindingReadMasked(BaseModel):
    id: UUID
    org_id: UUID
    dept_id: UUID | None = None
    scope_type: str
    langfuse_host: str
    langfuse_org_id: str
    langfuse_project_id: str
    langfuse_project_name: str | None = None
    public_key_masked: str
    secret_key_masked: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProvisionResponse(BaseModel):
    job: ProvisionJobRead
    binding: BindingReadMasked | None = None


class ScopeOptionItem(BaseModel):
    id: UUID
    name: str


class DepartmentScopeOption(BaseModel):
    id: UUID
    name: str
    org_id: UUID


class ScopeOptionsResponse(BaseModel):
    role: str
    requires_filter_first: bool
    organizations: list[ScopeOptionItem]
    departments: list[DepartmentScopeOption]


class BindingReconciliationItem(BaseModel):
    binding_id: UUID
    org_id: UUID
    dept_id: UUID | None = None
    scope_type: str
    status: str
    issues: list[str] = []


class ReconciliationResponse(BaseModel):
    total: int
    healthy: int
    drifted: int
    failed: int
    items: list[BindingReconciliationItem]


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def _require_provisioning_admin(current_user: User) -> str:
    role = normalize_role(current_user.role)
    if role not in {"root", "super_admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only root or super admin can manage observability provisioning.",
        )
    return role


async def _admin_org_ids_for_user(session: DbSession, current_user: User) -> set[UUID]:
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


async def _ensure_org_access(session: DbSession, current_user: User, org_id: UUID) -> None:
    role = _require_provisioning_admin(current_user)
    if role == "root":
        return
    org_ids = await _admin_org_ids_for_user(session, current_user)
    if org_id not in org_ids:
        raise HTTPException(status_code=403, detail="Organization is outside your scope.")


async def _ensure_job_access(session: DbSession, current_user: User, job: ObservabilityProvisionJob) -> None:
    _require_provisioning_admin(current_user)
    if normalize_role(current_user.role) == "root":
        return
    org_ids = await _admin_org_ids_for_user(session, current_user)
    if not job.org_id or job.org_id not in org_ids:
        raise HTTPException(status_code=403, detail="Provisioning job is outside your scope.")


async def _resolve_binding_for_job(
    session: DbSession,
    job: ObservabilityProvisionJob,
) -> LangfuseBinding | None:
    stmt = select(LangfuseBinding).where(
        LangfuseBinding.scope_type == job.scope_type,
        LangfuseBinding.org_id == job.org_id,
        LangfuseBinding.is_active.is_(True),
    )
    if job.scope_type == "department":
        stmt = stmt.where(LangfuseBinding.dept_id == job.dept_id)
    else:
        stmt = stmt.where(LangfuseBinding.dept_id.is_(None))
    return (await session.exec(stmt)).first()


def _serialize_job(job: ObservabilityProvisionJob) -> ProvisionJobRead:
    return ProvisionJobRead(
        id=job.id,
        idempotency_key=job.idempotency_key,
        scope_type=job.scope_type,
        org_id=job.org_id,
        dept_id=job.dept_id,
        status=job.status,
        retry_count=int(job.retry_count or 0),
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )


def _serialize_binding(service, binding: LangfuseBinding) -> BindingReadMasked:
    try:
        public_key = service.decrypt_secret(binding.public_key_encrypted)
    except Exception:
        public_key = ""
    try:
        secret_key = service.decrypt_secret(binding.secret_key_encrypted)
    except Exception:
        secret_key = ""

    return BindingReadMasked(
        id=binding.id,
        org_id=binding.org_id,
        dept_id=binding.dept_id,
        scope_type=binding.scope_type,
        langfuse_host=binding.langfuse_host,
        langfuse_org_id=binding.langfuse_org_id,
        langfuse_project_id=binding.langfuse_project_id,
        langfuse_project_name=binding.langfuse_project_name,
        public_key_masked=_mask_key(public_key),
        secret_key_masked=_mask_key(secret_key),
        is_active=bool(binding.is_active),
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


@router.post("/provision/org/{org_id}", response_model=ProvisionResponse)
async def provision_org_observability(
    org_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ProvisionResponse:
    await _ensure_org_access(session, current_user, org_id)
    org = await session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")

    service = get_langfuse_provisioning_service()
    try:
        binding = await service.provision_org_admin_project(
            session,
            org=org,
            actor=current_user,
            idempotency_key=f"org-admin:{org.id}",
        )
        await session.commit()
    except LangfuseProvisioningError as exc:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Langfuse provisioning failed: {exc}") from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Provisioning failed: {exc}") from exc

    job = (
        await session.exec(
            select(ObservabilityProvisionJob).where(
                ObservabilityProvisionJob.idempotency_key == f"org-admin:{org.id}"
            )
        )
    ).first()
    if not job:
        synthetic_job = ProvisionJobRead(
            id=uuid4(),
            idempotency_key=f"org-admin:{org.id}",
            scope_type="org_admin",
            org_id=org.id,
            dept_id=None,
            status="success",
            retry_count=0,
            updated_at=datetime.now(timezone.utc),
        )
        return ProvisionResponse(job=synthetic_job, binding=_serialize_binding(service, binding))
    return ProvisionResponse(job=_serialize_job(job), binding=_serialize_binding(service, binding))


@router.post("/provision/dept/{dept_id}", response_model=ProvisionResponse)
async def provision_department_observability(
    dept_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ProvisionResponse:
    _require_provisioning_admin(current_user)
    department = await session.get(Department, dept_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found.")
    await _ensure_org_access(session, current_user, department.org_id)
    org = await session.get(Organization, department.org_id)
    if not org:
        raise HTTPException(status_code=400, detail="Department organization mapping is invalid.")

    service = get_langfuse_provisioning_service()
    idem_key = f"department:{department.id}"
    try:
        binding = await service.provision_department_project(
            session,
            org=org,
            department=department,
            actor=current_user,
            idempotency_key=idem_key,
        )
        await session.commit()
    except LangfuseProvisioningError as exc:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Langfuse provisioning failed: {exc}") from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Provisioning failed: {exc}") from exc

    job = (
        await session.exec(
            select(ObservabilityProvisionJob).where(
                ObservabilityProvisionJob.idempotency_key == idem_key
            )
        )
    ).first()
    if not job:
        synthetic_job = ProvisionJobRead(
            id=uuid4(),
            idempotency_key=idem_key,
            scope_type="department",
            org_id=department.org_id,
            dept_id=department.id,
            status="success",
            retry_count=0,
            updated_at=datetime.now(timezone.utc),
        )
        return ProvisionResponse(job=synthetic_job, binding=_serialize_binding(service, binding))
    return ProvisionResponse(job=_serialize_job(job), binding=_serialize_binding(service, binding))


@router.post("/provision/retry/{job_id}", response_model=ProvisionResponse)
async def retry_observability_provisioning(
    job_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ProvisionResponse:
    job = await session.get(ObservabilityProvisionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Provisioning job not found.")
    await _ensure_job_access(session, current_user, job)

    if not job.org_id:
        raise HTTPException(status_code=400, detail="Provisioning job has no organization context.")
    org = await session.get(Organization, job.org_id)
    if not org:
        raise HTTPException(status_code=400, detail="Organization not found for provisioning job.")

    service = get_langfuse_provisioning_service()
    try:
        if job.scope_type == "org_admin":
            await service.provision_org_admin_project(
                session,
                org=org,
                actor=current_user,
                idempotency_key=job.idempotency_key,
            )
        elif job.scope_type == "department":
            if not job.dept_id:
                raise HTTPException(status_code=400, detail="Department provisioning job has no dept_id.")
            department = await session.get(Department, job.dept_id)
            if not department:
                raise HTTPException(status_code=400, detail="Department not found for provisioning job.")
            await service.provision_department_project(
                session,
                org=org,
                department=department,
                actor=current_user,
                idempotency_key=job.idempotency_key,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported job scope_type={job.scope_type}")
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except LangfuseProvisioningError as exc:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Langfuse provisioning failed: {exc}") from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Provisioning retry failed: {exc}") from exc

    refreshed_job = await session.get(ObservabilityProvisionJob, job_id)
    if not refreshed_job:
        raise HTTPException(status_code=500, detail="Provisioning job disappeared after retry.")
    binding = await _resolve_binding_for_job(session, refreshed_job)
    return ProvisionResponse(
        job=_serialize_job(refreshed_job),
        binding=_serialize_binding(service, binding) if binding else None,
    )


@router.get("/provision/status/{job_id}", response_model=ProvisionJobRead)
async def get_observability_provisioning_status(
    job_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ProvisionJobRead:
    job = await session.get(ObservabilityProvisionJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Provisioning job not found.")
    await _ensure_job_access(session, current_user, job)
    return _serialize_job(job)


@router.get("/config", response_model=list[BindingReadMasked])
async def get_observability_config(
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[BindingReadMasked]:
    role = _require_provisioning_admin(current_user)
    stmt = select(LangfuseBinding).where(LangfuseBinding.is_active.is_(True))
    if role == "super_admin":
        org_ids = await _admin_org_ids_for_user(session, current_user)
        if not org_ids:
            return []
        stmt = stmt.where(LangfuseBinding.org_id.in_(list(org_ids)))
    stmt = stmt.order_by(
        LangfuseBinding.scope_type.asc(),
        LangfuseBinding.org_id.asc(),
        LangfuseBinding.dept_id.asc(),
    )
    rows = (await session.exec(stmt)).all()

    service = get_langfuse_provisioning_service()
    return [_serialize_binding(service, row) for row in rows]


@router.post("/provision/reconcile", response_model=ReconciliationResponse)
async def reconcile_observability_bindings(
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
    org_id: UUID | None = None,
) -> ReconciliationResponse:
    role = _require_provisioning_admin(current_user)
    stmt = select(LangfuseBinding).where(LangfuseBinding.is_active.is_(True))

    if org_id is not None:
        await _ensure_org_access(session, current_user, org_id)
        stmt = stmt.where(LangfuseBinding.org_id == org_id)
    elif role == "super_admin":
        org_ids = await _admin_org_ids_for_user(session, current_user)
        if not org_ids:
            return ReconciliationResponse(total=0, healthy=0, drifted=0, failed=0, items=[])
        stmt = stmt.where(LangfuseBinding.org_id.in_(list(org_ids)))

    bindings = list((await session.exec(stmt.order_by(LangfuseBinding.created_at.asc()))).all())
    if not bindings:
        return ReconciliationResponse(total=0, healthy=0, drifted=0, failed=0, items=[])

    service = get_langfuse_provisioning_service()
    try:
        raw_results = await asyncio.to_thread(service.reconcile_bindings, bindings)
    except LangfuseProvisioningError as exc:
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {exc}") from exc

    binding_by_id = {str(binding.id): binding for binding in bindings}
    items: list[BindingReconciliationItem] = []
    healthy = 0
    drifted = 0
    failed = 0

    for result in raw_results:
        binding = binding_by_id.get(result.binding_id)
        if not binding:
            continue
        if result.status == "healthy":
            healthy += 1
        elif result.status == "drift":
            drifted += 1
        else:
            failed += 1
        items.append(
            BindingReconciliationItem(
                binding_id=binding.id,
                org_id=binding.org_id,
                dept_id=binding.dept_id,
                scope_type=binding.scope_type,
                status=result.status,
                issues=list(result.issues or []),
            )
        )

    return ReconciliationResponse(
        total=len(items),
        healthy=healthy,
        drifted=drifted,
        failed=failed,
        items=items,
    )


@router.get("/scope-options", response_model=ScopeOptionsResponse)
async def get_observability_scope_options(
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ScopeOptionsResponse:
    role = normalize_role(current_user.role)

    org_rows: list[tuple[UUID, str]] = []
    dept_rows: list[tuple[UUID, str, UUID]] = []

    if role == "root":
        org_rows = (await session.exec(select(Organization.id, Organization.name).order_by(Organization.name))).all()
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id).where(
                    Department.status == "active"
                ).order_by(Department.name)
            )
        ).all()
    elif role == "super_admin":
        org_ids = await _admin_org_ids_for_user(session, current_user)
        if org_ids:
            org_rows = (
                await session.exec(
                    select(Organization.id, Organization.name).where(
                        Organization.id.in_(list(org_ids))
                    ).order_by(Organization.name)
                )
            ).all()
            dept_rows = (
                await session.exec(
                    select(Department.id, Department.name, Department.org_id).where(
                        Department.org_id.in_(list(org_ids)),
                        Department.status == "active",
                    ).order_by(Department.name)
                )
            ).all()
    else:
        org_rows = (
            await session.exec(
                select(Organization.id, Organization.name)
                .join(
                    UserOrganizationMembership,
                    UserOrganizationMembership.org_id == Organization.id,
                )
                .where(
                    UserOrganizationMembership.user_id == current_user.id,
                    UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                )
                .order_by(Organization.name)
            )
        ).all()
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id)
                .join(
                    UserDepartmentMembership,
                    UserDepartmentMembership.department_id == Department.id,
                )
                .where(
                    UserDepartmentMembership.user_id == current_user.id,
                    UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                )
                .order_by(Department.name)
            )
        ).all()

    return ScopeOptionsResponse(
        role=role,
        requires_filter_first=role in {"root", "super_admin"},
        organizations=[ScopeOptionItem(id=row[0], name=row[1]) for row in org_rows],
        departments=[DepartmentScopeOption(id=row[0], name=row[1], org_id=row[2]) for row in dept_rows],
    )
