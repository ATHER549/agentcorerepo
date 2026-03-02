"""REST endpoints for the model registry with approval-enforced promotion rules."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services import model_registry_service
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.model_approval_request.model import (
    ModelApprovalRequest,
    ModelApprovalRequestType,
)
from agentcore.services.database.models.model_audit_log.model import ModelAuditLog
from agentcore.services.database.models.model_registry.model import (
    ModelApprovalStatus,
    ModelEnvironment,
    ModelRegistry,
    ModelRegistryCreate,
    ModelRegistryRead,
    ModelRegistryUpdate,
    ModelVisibilityScope,
    TestConnectionRequest,
    TestConnectionResponse,
)
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models/registry", tags=["Model Registry"])


def _normalize_environment(value: str | None) -> str:
    normalized = (value or ModelEnvironment.TEST.value).strip().lower()
    if normalized == "dev":
        normalized = ModelEnvironment.TEST.value
    if normalized not in {ModelEnvironment.TEST.value, ModelEnvironment.UAT.value, ModelEnvironment.PROD.value}:
        raise HTTPException(status_code=400, detail=f"Unsupported environment '{value}'")
    return normalized


def _normalize_visibility_scope(value: str | None) -> str:
    normalized = (value or ModelVisibilityScope.PRIVATE.value).strip().lower()
    if normalized not in {
        ModelVisibilityScope.PRIVATE.value,
        ModelVisibilityScope.DEPARTMENT.value,
        ModelVisibilityScope.ORGANIZATION.value,
    }:
        raise HTTPException(status_code=400, detail=f"Unsupported visibility_scope '{value}'")
    return normalized


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    normalized = _normalize_role_variants(getattr(current_user, "role", ""))
    return "root" in normalized


def _normalize_role_variants(role: object) -> set[str]:
    raw = str(role or "").strip()
    if not raw:
        return set()
    lowered = raw.lower()
    normalized = {
        lowered,
        lowered.replace(" ", "_"),
        lowered.replace("-", "_"),
        lowered.replace(" ", "_").replace("-", "_"),
    }
    if "." in lowered:
        normalized.add(lowered.split(".")[-1].replace("-", "_"))
    normalized.add(normalize_role(raw))
    return normalized


def _can_self_approve(current_user: CurrentActiveUser) -> bool:
    normalized = _normalize_role_variants(getattr(current_user, "role", ""))
    return bool(
        normalized.intersection(
            {
                "root",
                "root_admin",
                "super_admin",
                "superadmin",
                "department_admin",
                "departmentadmin",
                "dept_admin",
                "deptadmin",
            }
        )
    )


async def _require_any_permission(current_user: CurrentActiveUser, permissions: set[str]) -> None:
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


async def _validate_departments_exist_for_org(session: DbSession, org_id: UUID, dept_ids: list[UUID]) -> None:
    if not dept_ids:
        return
    rows = (
        await session.exec(
            select(Department.id).where(Department.org_id == org_id, Department.id.in_(dept_ids))
        )
    ).all()
    if len({str(r if isinstance(r, UUID) else r[0]) for r in rows}) != len({str(d) for d in dept_ids}):
        raise HTTPException(status_code=400, detail="One or more public_dept_ids are invalid for org_id")


async def _get_department_ids_for_org(session: DbSession, org_id: UUID) -> list[UUID]:
    rows = (await session.exec(select(Department.id).where(Department.org_id == org_id))).all()
    return [r if isinstance(r, UUID) else r[0] for r in rows]


async def _resolve_department_admin_approver(
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None,
    dept_id: UUID | None,
) -> UUID:
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


async def _resolve_super_admin_approver(session: DbSession, current_user: CurrentActiveUser) -> UUID:
    stmt = select(User).where(User.role == "super_admin", User.id != current_user.id).order_by(User.create_at.asc())
    row = (await session.exec(stmt)).first()
    if not row:
        if _can_self_approve(current_user):
            return current_user.id
        raise HTTPException(status_code=400, detail="No Super Admin approver available")
    return row.id


async def _append_audit(
    session: DbSession,
    *,
    model_id: UUID | None,
    actor_id: UUID | None,
    action: str,
    org_id: UUID | None = None,
    dept_id: UUID | None = None,
    from_environment: str | None = None,
    to_environment: str | None = None,
    from_visibility: str | None = None,
    to_visibility: str | None = None,
    details: dict | None = None,
    message: str | None = None,
) -> None:
    session.add(
        ModelAuditLog(
            model_id=model_id,
            actor_id=actor_id,
            action=action,
            org_id=org_id,
            dept_id=dept_id,
            from_environment=from_environment,
            to_environment=to_environment,
            from_visibility=from_visibility,
            to_visibility=to_visibility,
            details=details,
            message=message,
        )
    )


def _can_access_model(
    row: ModelRegistry,
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return True

    role = normalize_role(str(current_user.role))
    user_id = str(current_user.id)

    if role == "super_admin" and row.org_id and row.org_id in org_ids:
        return True
    if role == "department_admin":
        dept_ids = {str(d) for _, d in dept_pairs}
        scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
        if row.dept_id and str(row.dept_id) in dept_ids:
            return True
        if scoped_public_depts.intersection(dept_ids):
            return True

    if (row.approval_status or ModelApprovalStatus.APPROVED.value) != ModelApprovalStatus.APPROVED.value:
        return str(row.requested_by or "") == user_id or str(row.request_to or "") == user_id

    visibility_scope = _normalize_visibility_scope(getattr(row, "visibility_scope", None))
    if visibility_scope == ModelVisibilityScope.PRIVATE.value:
        return (
            str(row.created_by_id or "") == user_id
            or str(row.requested_by or "") == user_id
            or str(getattr(row, "created_by", "")) == str(getattr(current_user, "username", ""))
        )
    if visibility_scope == ModelVisibilityScope.DEPARTMENT.value:
        dept_ids = {str(d) for _, d in dept_pairs}
        scoped_public_depts = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
        if row.dept_id and str(row.dept_id) in dept_ids:
            return True
        return bool(scoped_public_depts.intersection(dept_ids))
    if visibility_scope == ModelVisibilityScope.ORGANIZATION.value:
        return bool(row.org_id and row.org_id in org_ids)
    return False


def _is_department_scoped_model(row: ModelRegistry, dept_pairs: list[tuple[UUID, UUID]]) -> bool:
    user_dept_ids = {str(dept_id) for _, dept_id in dept_pairs}
    model_dept_ids = {str(v) for v in (getattr(row, "public_dept_ids", None) or [])}
    if row.dept_id:
        model_dept_ids.add(str(row.dept_id))
    return bool(model_dept_ids.intersection(user_dept_ids))


def _can_delete_model(
    row: ModelRegistry,
    current_user: CurrentActiveUser,
    *,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return True

    normalized_roles = _normalize_role_variants(getattr(current_user, "role", ""))
    user_id = str(current_user.id)
    is_creator = str(getattr(row, "created_by_id", "") or "") == user_id

    # Global rule: the creator can delete their own model.
    if is_creator:
        return True

    # Developer/Business User: creator-only delete.
    if normalized_roles.intersection({"developer", "business_user"}):
        return False

    # Department Admin:
    # - can delete models approved by self
    # - can delete models in their department scope
    if normalized_roles.intersection({"department_admin", "dept_admin", "departmentadmin", "deptadmin"}):
        if str(getattr(row, "reviewed_by", "") or "") == user_id:
            return True
        return _is_department_scoped_model(row, dept_pairs)

    # Super Admin: can delete any model within their org scope.
    if normalized_roles.intersection({"super_admin", "superadmin"}):
        return bool(row.org_id and row.org_id in org_ids)

    return False


async def _create_model_approval_request(
    session: DbSession,
    *,
    model_id: UUID,
    org_id: UUID | None,
    dept_id: UUID | None,
    request_type: ModelApprovalRequestType,
    source_environment: str,
    target_environment: str,
    final_target_environment: str | None,
    visibility_requested: str,
    requested_by: UUID,
    request_to: UUID,
) -> ModelApprovalRequest:
    req = ModelApprovalRequest(
        model_id=model_id,
        org_id=org_id,
        dept_id=dept_id,
        request_type=request_type,
        source_environment=source_environment,
        target_environment=target_environment,
        final_target_environment=final_target_environment,
        visibility_requested=visibility_requested,
        requested_by=requested_by,
        request_to=request_to,
    )
    session.add(req)
    await session.flush()
    return req


async def _has_pending_model_request(
    session: DbSession,
    *,
    model_id: UUID,
    request_type: ModelApprovalRequestType | None = None,
) -> bool:
    stmt = select(ModelApprovalRequest).where(
        ModelApprovalRequest.model_id == model_id,
        ModelApprovalRequest.decision == None,  # noqa: E711
    )
    if request_type is not None:
        stmt = stmt.where(ModelApprovalRequest.request_type == request_type)
    existing = (await session.exec(stmt.order_by(ModelApprovalRequest.requested_at.desc()))).first()
    return existing is not None


def _next_environment(current_env: str) -> str | None:
    normalized = _normalize_environment(current_env)
    if normalized == ModelEnvironment.TEST.value:
        return ModelEnvironment.UAT.value
    if normalized == ModelEnvironment.UAT.value:
        return ModelEnvironment.PROD.value
    return None


def _requires_super_admin_approval(*, target_environment: str, visibility_scope: str) -> bool:
    normalized_target = _normalize_environment(target_environment)
    normalized_visibility = _normalize_visibility_scope(visibility_scope)
    return (
        normalized_target == ModelEnvironment.PROD.value
        or normalized_visibility == ModelVisibilityScope.ORGANIZATION.value
    )


async def _resolve_approver_for_model_request(
    session: DbSession,
    current_user: CurrentActiveUser,
    *,
    target_environment: str,
    visibility_scope: str,
    org_id: UUID | None,
    dept_id: UUID | None,
) -> UUID:
    if _requires_super_admin_approval(
        target_environment=target_environment,
        visibility_scope=visibility_scope,
    ):
        return await _resolve_super_admin_approver(session, current_user)
    return await _resolve_department_admin_approver(session, current_user, org_id, dept_id)


class PromoteModelPayload(ModelRegistryUpdate):
    target_environment: str


class ModelVisibilityChangePayload(ModelRegistryUpdate):
    visibility_scope: str


@router.get("/", response_model=list[ModelRegistryRead])
async def list_registry_models(
    session: DbSession,
    current_user: CurrentActiveUser,
    provider: str | None = None,
    environment: str | None = None,
    model_type: str | None = None,
    active_only: bool = True,
):
    """List visible models only (tenant + visibility aware)."""
    await _require_any_permission(current_user, {"view_model_catalogue_page", "view_models"})
    rows = await model_registry_service.get_models(
        session,
        provider=provider,
        environment=_normalize_environment(environment) if environment else None,
        model_type=model_type,
        active_only=active_only,
    )
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    visible = [
        row
        for row in rows
        if _can_access_model(ModelRegistry.model_validate(row.model_dump()), current_user, org_ids, dept_pairs)
    ]
    return visible


@router.post("/", response_model=ModelRegistryRead, status_code=201)
async def create_registry_model(
    body: ModelRegistryCreate,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Create model through approval-safe flow."""
    await _require_any_permission(current_user, {"add_new_model", "request_new_model"})
    desired_environment = _normalize_environment(body.environment)
    visibility_scope = _normalize_visibility_scope(getattr(body, "visibility_scope", None))
    requested_public_dept_ids = list(getattr(body, "public_dept_ids", None) or [])
    now = datetime.now(timezone.utc)

    if not body.created_by and current_user:
        body.created_by = current_user.username
    body.created_by_id = current_user.id
    body.visibility_scope = visibility_scope

    user_role = normalize_role(str(current_user.role))
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)

    if body.org_id and user_role != "root" and body.org_id not in org_ids:
        raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
    if body.dept_id:
        dept_set = {dept for _, dept in dept_pairs}
        if user_role not in {"root", "super_admin"} and body.dept_id not in dept_set:
            raise HTTPException(status_code=403, detail="dept_id must belong to your department scope")

    if visibility_scope == ModelVisibilityScope.DEPARTMENT.value:
        if user_role in {"root", "super_admin"}:
            if not body.org_id:
                if not org_ids:
                    raise HTTPException(status_code=403, detail="No active organization scope found for requester")
                body.org_id = sorted(org_ids, key=lambda x: str(x))[0]
            if not requested_public_dept_ids and body.dept_id:
                requested_public_dept_ids = [body.dept_id]
            if not requested_public_dept_ids:
                requested_public_dept_ids = await _get_department_ids_for_org(session, body.org_id)
            if not requested_public_dept_ids:
                raise HTTPException(status_code=400, detail="No departments found for selected org_id")
            if requested_public_dept_ids:
                requested_public_dept_ids = list(dict.fromkeys(requested_public_dept_ids))
                if not body.org_id:
                    first_dept = (
                        await session.exec(select(Department).where(Department.id == requested_public_dept_ids[0]))
                    ).first()
                    if not first_dept:
                        raise HTTPException(status_code=400, detail="Invalid department selected")
                    body.org_id = first_dept.org_id
                await _validate_departments_exist_for_org(session, body.org_id, requested_public_dept_ids)
                body.dept_id = requested_public_dept_ids[0]
                body.public_dept_ids = requested_public_dept_ids
        else:
            if not dept_pairs:
                raise HTTPException(status_code=403, detail="No active department scope found for requester")
            current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
            body.org_id = current_org_id
            body.dept_id = current_dept_id
            body.public_dept_ids = [current_dept_id]
    else:
        body.public_dept_ids = None

    if not body.org_id and dept_pairs:
        body.org_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0][0]
    if not body.dept_id and dept_pairs:
        body.dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0][1]

    await _validate_scope_refs(session, body.org_id, body.dept_id)

    body.environment = desired_environment
    body.requested_by = current_user.id
    body.requested_at = now

    is_super_admin_creator = user_role in {"root", "super_admin"}
    is_department_admin_creator = user_role == "department_admin"
    auto_approve = (
        is_super_admin_creator
        or (is_department_admin_creator and visibility_scope != ModelVisibilityScope.ORGANIZATION.value)
        or (desired_environment == ModelEnvironment.TEST.value and visibility_scope == ModelVisibilityScope.PRIVATE.value)
    )
    if auto_approve:
        body.approval_status = ModelApprovalStatus.APPROVED.value
        body.reviewed_by = current_user.id
        body.reviewed_at = now
        body.is_active = True
    else:
        body.approval_status = ModelApprovalStatus.PENDING.value
        body.is_active = False
        body.request_to = None

    created = await model_registry_service.create_model(session, body)
    created_row = await session.get(ModelRegistry, created.id)
    if created_row is None:
        raise HTTPException(status_code=500, detail="Created model not found")

    await _append_audit(
        session,
        model_id=created.id,
        actor_id=current_user.id,
        action="model.create",
        org_id=created_row.org_id,
        dept_id=created_row.dept_id,
        to_environment=desired_environment,
        to_visibility=visibility_scope,
        details={"requested_environment": desired_environment},
        message="Model created",
    )

    if not auto_approve:
        # Approver policy:
        # - PROD target (any visibility): super admin
        # - ORGANIZATION visibility (any env): super admin
        # - otherwise: department admin
        request_to = await _resolve_approver_for_model_request(
            session,
            current_user,
            target_environment=desired_environment,
            visibility_scope=visibility_scope,
            org_id=created_row.org_id,
            dept_id=created_row.dept_id,
        )

        if request_to == current_user.id and _can_self_approve(current_user):
            created_row.approval_status = ModelApprovalStatus.APPROVED.value
            created_row.reviewed_by = current_user.id
            created_row.reviewed_at = now
            created_row.is_active = True
            created_row.request_to = None
            session.add(created_row)
            await _append_audit(
                session,
                model_id=created.id,
                actor_id=current_user.id,
                action="model.create.auto_approved",
                org_id=created_row.org_id,
                dept_id=created_row.dept_id,
                from_environment=desired_environment,
                to_environment=desired_environment,
                from_visibility=visibility_scope,
                to_visibility=visibility_scope,
                details={"auto_approved": True, "reason": "requester_is_admin_approver"},
                message="Model request auto-approved by admin requester",
            )
        else:
            if request_to == current_user.id:
                raise HTTPException(status_code=400, detail="No user can approve their own request")

            await _create_model_approval_request(
                session,
                model_id=created.id,
                org_id=created_row.org_id,
                dept_id=created_row.dept_id,
                request_type=ModelApprovalRequestType.CREATE,
                source_environment=desired_environment,
                target_environment=desired_environment,
                final_target_environment=None,
                visibility_requested=visibility_scope,
                requested_by=current_user.id,
                request_to=request_to,
            )

            created_row.request_to = request_to
            session.add(created_row)

            await _append_audit(
                session,
                model_id=created.id,
                actor_id=current_user.id,
                action="model.create.requested",
                org_id=created_row.org_id,
                dept_id=created_row.dept_id,
                from_environment=desired_environment,
                to_environment=desired_environment,
                from_visibility=visibility_scope,
                to_visibility=visibility_scope,
                details={"requested_environment": desired_environment, "requested_visibility": visibility_scope},
                message="Model onboarding approval request created",
            )

    await session.commit()
    await session.refresh(created_row)
    return ModelRegistryRead.from_orm_model(created_row)


@router.post("/{model_id}/promote", response_model=ModelRegistryRead)
async def request_model_promotion(
    model_id: UUID,
    body: PromoteModelPayload,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"request_new_model", "add_new_model"})
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")

    target_environment = _normalize_environment(body.target_environment)
    current_environment = _normalize_environment(row.environment)
    allowed_next = _next_environment(current_environment)
    if not allowed_next or target_environment != allowed_next:
        raise HTTPException(status_code=400, detail="Invalid promotion path. Use DEV->UAT or UAT->PROD only")
    if await _has_pending_model_request(session, model_id=row.id, request_type=ModelApprovalRequestType.PROMOTE):
        raise HTTPException(status_code=400, detail="A promotion request is already pending for this model")

    approver_id = await _resolve_approver_for_model_request(
        session,
        current_user,
        target_environment=target_environment,
        visibility_scope=row.visibility_scope,
        org_id=row.org_id,
        dept_id=row.dept_id,
    )
    if approver_id == current_user.id and _can_self_approve(current_user):
        now = datetime.now(timezone.utc)
        row.environment = target_environment
        row.approval_status = ModelApprovalStatus.APPROVED.value
        row.requested_by = current_user.id
        row.request_to = None
        row.requested_at = None
        row.reviewed_by = current_user.id
        row.reviewed_at = now
        row.is_active = True
        session.add(row)
        await _append_audit(
            session,
            model_id=row.id,
            actor_id=current_user.id,
            action="model.promotion.auto_approved",
            org_id=row.org_id,
            dept_id=row.dept_id,
            from_environment=current_environment,
            to_environment=target_environment,
            details={"auto_approved": True, "reason": "requester_is_admin_approver"},
            message="Promotion auto-approved by admin requester",
        )
        await session.commit()
        await session.refresh(row)
        return ModelRegistryRead.from_orm_model(row)
    if approver_id == current_user.id:
        raise HTTPException(status_code=400, detail="No user can approve their own request")

    now = datetime.now(timezone.utc)
    row.approval_status = ModelApprovalStatus.PENDING.value
    row.requested_by = current_user.id
    row.request_to = approver_id
    row.requested_at = now
    row.is_active = False
    session.add(row)

    await _create_model_approval_request(
        session,
        model_id=row.id,
        org_id=row.org_id,
        dept_id=row.dept_id,
        request_type=ModelApprovalRequestType.PROMOTE,
        source_environment=current_environment,
        target_environment=target_environment,
        final_target_environment=None,
        visibility_requested=row.visibility_scope,
        requested_by=current_user.id,
        request_to=approver_id,
    )
    await _append_audit(
        session,
        model_id=row.id,
        actor_id=current_user.id,
        action="model.promotion.requested",
        org_id=row.org_id,
        dept_id=row.dept_id,
        from_environment=current_environment,
        to_environment=target_environment,
        message="Promotion request created",
    )
    await session.commit()
    await session.refresh(row)
    return ModelRegistryRead.from_orm_model(row)


@router.post("/{model_id}/visibility", response_model=ModelRegistryRead)
async def request_model_visibility_change(
    model_id: UUID,
    body: ModelVisibilityChangePayload,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"request_new_model", "add_new_model"})
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if await _has_pending_model_request(session, model_id=row.id, request_type=ModelApprovalRequestType.VISIBILITY):
        raise HTTPException(status_code=400, detail="A visibility change request is already pending for this model")
    target_visibility = _normalize_visibility_scope(body.visibility_scope)
    if target_visibility == row.visibility_scope:
        return ModelRegistryRead.from_orm_model(row)

    approver_id = await _resolve_approver_for_model_request(
        session,
        current_user,
        target_environment=row.environment,
        visibility_scope=target_visibility,
        org_id=row.org_id,
        dept_id=row.dept_id,
    )
    if approver_id == current_user.id and _can_self_approve(current_user):
        now = datetime.now(timezone.utc)
        row.visibility_scope = target_visibility
        row.approval_status = ModelApprovalStatus.APPROVED.value
        row.requested_by = current_user.id
        row.request_to = None
        row.requested_at = None
        row.reviewed_by = current_user.id
        row.reviewed_at = now
        row.is_active = True
        session.add(row)
        await _append_audit(
            session,
            model_id=row.id,
            actor_id=current_user.id,
            action="model.visibility.auto_approved",
            org_id=row.org_id,
            dept_id=row.dept_id,
            from_visibility=row.visibility_scope,
            to_visibility=target_visibility,
            details={"auto_approved": True, "reason": "requester_is_admin_approver"},
            message="Visibility change auto-approved by admin requester",
        )
        await session.commit()
        await session.refresh(row)
        return ModelRegistryRead.from_orm_model(row)
    if approver_id == current_user.id:
        raise HTTPException(status_code=400, detail="No user can approve their own request")

    now = datetime.now(timezone.utc)
    row.approval_status = ModelApprovalStatus.PENDING.value
    row.requested_by = current_user.id
    row.request_to = approver_id
    row.requested_at = now
    session.add(row)

    await _create_model_approval_request(
        session,
        model_id=row.id,
        org_id=row.org_id,
        dept_id=row.dept_id,
        request_type=ModelApprovalRequestType.VISIBILITY,
        source_environment=_normalize_environment(row.environment),
        target_environment=_normalize_environment(row.environment),
        final_target_environment=None,
        visibility_requested=target_visibility,
        requested_by=current_user.id,
        request_to=approver_id,
    )
    await _append_audit(
        session,
        model_id=row.id,
        actor_id=current_user.id,
        action="model.visibility.requested",
        org_id=row.org_id,
        dept_id=row.dept_id,
        from_visibility=row.visibility_scope,
        to_visibility=target_visibility,
        message="Visibility change request created",
    )
    await session.commit()
    await session.refresh(row)
    return ModelRegistryRead.from_orm_model(row)


@router.get("/{model_id}", response_model=ModelRegistryRead)
async def get_registry_model(
    model_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"view_model_catalogue_page", "view_models"})
    model = await model_registry_service.get_model(session, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_access_model(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Model is outside your visibility scope")
    return model


@router.put("/{model_id}", response_model=ModelRegistryRead)
async def update_registry_model(
    model_id: UUID,
    body: ModelRegistryUpdate,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    await _require_any_permission(current_user, {"add_new_model", "request_new_model"})
    existing = await session.get(ModelRegistry, model_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Model not found")

    if body.environment and _normalize_environment(body.environment) != _normalize_environment(existing.environment):
        raise HTTPException(status_code=400, detail="Direct environment change is blocked. Use /promote flow")

    if body.visibility_scope and _normalize_visibility_scope(body.visibility_scope) != _normalize_visibility_scope(existing.visibility_scope):
        raise HTTPException(status_code=400, detail="Direct visibility change is blocked. Use /visibility flow")

    model = await model_registry_service.update_model(session, model_id, body)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    await _append_audit(
        session,
        model_id=model_id,
        actor_id=current_user.id,
        action="model.updated",
        org_id=existing.org_id,
        dept_id=existing.dept_id,
        message="Model metadata updated",
    )
    await session.commit()
    return model


@router.delete("/{model_id}", status_code=204)
async def delete_registry_model(
    model_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    allowed_roles = {
        "root",
        "root_admin",
        "super_admin",
        "superadmin",
        "department_admin",
        "departmentadmin",
        "dept_admin",
        "deptadmin",
        "developer",
        "business_user",
    }
    if not _normalize_role_variants(getattr(current_user, "role", "")).intersection(allowed_roles):
        raise HTTPException(status_code=403, detail="Your role is not allowed to delete models")

    row = await session.get(ModelRegistry, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")

    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_delete_model(row, current_user, org_ids=org_ids, dept_pairs=dept_pairs):
        raise HTTPException(status_code=403, detail="You are not allowed to delete this model")

    approval_rows = (
        await session.exec(select(ModelApprovalRequest).where(ModelApprovalRequest.model_id == model_id))
    ).all()
    for req in approval_rows:
        await session.delete(req)

    audit_rows = (
        await session.exec(select(ModelAuditLog).where(ModelAuditLog.model_id == model_id))
    ).all()
    for audit in audit_rows:
        audit.model_id = None
        session.add(audit)

    await _append_audit(
        session,
        model_id=None,
        actor_id=current_user.id,
        action="model.deleted",
        org_id=row.org_id,
        dept_id=row.dept_id,
        details={"deleted_model_id": str(model_id)},
        message="Model deleted",
    )
    await session.delete(row)
    await session.commit()


@router.get("/{model_id}/audit", response_model=list[dict])
async def get_model_audit_trail(
    model_id: UUID,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> list[dict]:
    await _require_any_permission(current_user, {"view_model_catalogue_page", "view_models", "view_model"})
    rows = (
        await session.exec(
            select(ModelAuditLog).where(ModelAuditLog.model_id == model_id).order_by(ModelAuditLog.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "model_id": str(r.model_id) if r.model_id else None,
            "action": r.action,
            "actor_id": str(r.actor_id) if r.actor_id else None,
            "org_id": str(r.org_id) if r.org_id else None,
            "dept_id": str(r.dept_id) if r.dept_id else None,
            "from_environment": r.from_environment,
            "to_environment": r.to_environment,
            "from_visibility": r.from_visibility,
            "to_visibility": r.to_visibility,
            "details": r.details,
            "message": r.message,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_model_connection(
    body: TestConnectionRequest,
    current_user: CurrentActiveUser,
):
    try:
        provider_name = body.provider.lower()
        provider_config: dict = body.provider_config or {}
        api_key = body.api_key or ""
        base_url = body.base_url or ""
        model = _build_test_model(
            provider_name=provider_name,
            model_name=body.model_name,
            api_key=api_key,
            base_url=base_url,
            provider_config=provider_config,
        )
        from langchain_core.messages import HumanMessage

        start = time.perf_counter()
        ai_message = await model.ainvoke([HumanMessage(content="Hello")])
        latency_ms = (time.perf_counter() - start) * 1000

        content = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        return TestConnectionResponse(
            success=True,
            message=f"Model responded: {content[:100]}",
            latency_ms=round(latency_ms, 1),
        )
    except Exception as e:
        logger.warning("Test connection failed for %s/%s: %s", body.provider, body.model_name, e)
        return TestConnectionResponse(success=False, message=str(e))


def _build_test_model(
    *,
    provider_name: str,
    model_name: str,
    api_key: str,
    base_url: str,
    provider_config: dict,
):
    if provider_name == "openai":
        from langchain_openai import ChatOpenAI

        kwargs = {"model": model_name, "api_key": api_key, "max_tokens": 50, "streaming": False}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    if provider_name == "azure":
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_deployment=provider_config.get("azure_deployment", model_name),
            azure_endpoint=base_url,
            api_key=api_key,
            api_version=provider_config.get("api_version", "2024-02-15-preview"),
            max_tokens=50,
            streaming=False,
        )

    if provider_name == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,
            api_key=api_key,
            max_tokens=50,
            streaming=False,
        )

    if provider_name == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            max_output_tokens=50,
        )

    if provider_name == "groq":
        from langchain_groq import ChatGroq

        kwargs = {"model": model_name, "api_key": api_key, "max_tokens": 50, "streaming": False}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatGroq(**kwargs)

    if provider_name == "openai_compatible":
        from langchain_openai import ChatOpenAI

        custom_headers = provider_config.get("custom_headers", {})
        kwargs = {
            "model": model_name,
            "api_key": api_key or "not-needed",
            "base_url": base_url,
            "max_tokens": 50,
            "streaming": False,
        }
        if custom_headers:
            kwargs["default_headers"] = custom_headers
        return ChatOpenAI(**kwargs)

    msg = f"Unsupported provider for test connection: {provider_name}"
    raise ValueError(msg)


@router.post("/test-embedding-connection", response_model=TestConnectionResponse)
async def test_embedding_connection(
    body: TestConnectionRequest,
    current_user: CurrentActiveUser,
):
    try:
        provider_name = body.provider.lower()
        provider_config: dict = body.provider_config or {}
        api_key = body.api_key or ""
        base_url = body.base_url or ""

        embeddings = _build_test_embeddings(
            provider_name=provider_name,
            model_name=body.model_name,
            api_key=api_key,
            base_url=base_url,
            provider_config=provider_config,
        )

        start = time.perf_counter()
        result = await embeddings.aembed_query("Hello")
        latency_ms = (time.perf_counter() - start) * 1000

        dim = len(result) if result else 0
        return TestConnectionResponse(
            success=True,
            message=f"Embedding generated: {dim} dimensions",
            latency_ms=round(latency_ms, 1),
        )
    except Exception as e:
        logger.warning("Test embedding connection failed for %s/%s: %s", body.provider, body.model_name, e)
        return TestConnectionResponse(success=False, message=str(e))


def _build_test_embeddings(
    *,
    provider_name: str,
    model_name: str,
    api_key: str,
    base_url: str,
    provider_config: dict,
):
    if provider_name == "openai":
        from langchain_openai import OpenAIEmbeddings

        kwargs: dict = {"model": model_name, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAIEmbeddings(**kwargs)

    if provider_name == "azure":
        from langchain_openai import AzureOpenAIEmbeddings

        return AzureOpenAIEmbeddings(
            model=model_name,
            azure_endpoint=base_url or provider_config.get("azure_endpoint", ""),
            azure_deployment=provider_config.get("azure_deployment", model_name),
            api_version=provider_config.get("api_version", "2025-10-01-preview"),
            api_key=api_key,
        )

    if provider_name == "google":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=model_name,
            google_api_key=api_key,
        )

    if provider_name in ("openai_compatible", "groq", "anthropic"):
        from langchain_openai import OpenAIEmbeddings

        kwargs = {
            "model": model_name,
            "api_key": api_key or "not-needed",
        }
        if base_url:
            kwargs["base_url"] = base_url
        custom_headers = provider_config.get("custom_headers", {})
        if custom_headers:
            kwargs["default_headers"] = custom_headers
        return OpenAIEmbeddings(**kwargs)

    msg = f"Unsupported provider for embedding test connection: {provider_name}"
    raise ValueError(msg)
