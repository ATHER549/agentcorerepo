from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from datetime import datetime, timezone, date, time, timedelta
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession

logger = logging.getLogger(__name__)

# Region config — read from env vars
_REGION_CODE = os.getenv("REGION_CODE", "")
_REGION_GATEWAY_URL = os.getenv("REGION_GATEWAY_URL", "").strip()
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.agent_bundle.model import AgentBundle, BundleTypeEnum
from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd
from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT
from agentcore.services.database.models.approval_request.model import ApprovalRequest
from agentcore.services.database.models.agent_registry.model import AgentRegistryRating
from agentcore.services.database.models.agent_publish_recipient.model import AgentPublishRecipient
from agentcore.services.database.models.hitl_request.model import HITLRequest
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.orch_conversation.model import OrchConversationTable
from agentcore.services.database.models.role.model import Role
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.database.models.guardrail_catalogue.model import GuardrailCatalogue
from agentcore.services.database.models.guardrail_execution_log.model import GuardrailExecutionLog

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Region-aware proxy: if X-Region-Code header is present and user is root,
# forward the request to the region-gateway instead of querying local DB.
# ---------------------------------------------------------------------------

async def _maybe_proxy_to_region(
    request: Request,
    current_user: CurrentActiveUser,
    section_path: str,
) -> dict | None:
    """If this is a cross-region request, proxy it and return the response.

    Returns None if this is a local request (no proxy needed).
    Raises HTTPException if the user is not root or the proxy fails.
    """
    region_code = request.headers.get("X-Region-Code", "").strip()
    if not region_code:
        return None

    # Same region as this deployment — no proxy needed
    if region_code.upper() == _REGION_CODE.upper():
        return None

    # Only root can access cross-region data
    role = str(getattr(current_user, "role", "")).lower()
    if role != "root":
        raise HTTPException(status_code=403, detail="Cross-region access requires root role")

    # Region gateway must be configured to proxy cross-region requests
    if not _REGION_GATEWAY_URL:
        raise HTTPException(status_code=400, detail="Cross-region proxy not configured on this deployment")

    # Forward to region-gateway
    gateway_url = f"{_REGION_GATEWAY_URL}/api/regions/{region_code}/dashboard/{section_path}"
    query_params = dict(request.query_params)
    query_params["caller"] = str(current_user.id)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(gateway_url, params=query_params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Region gateway returned %d for %s: %s", e.response.status_code, region_code, e)
        raise HTTPException(status_code=e.response.status_code, detail=f"Region '{region_code}' error")
    except Exception as e:
        logger.error("Region gateway error for %s: %s", region_code, e)
        raise HTTPException(status_code=502, detail=f"Cannot reach region '{region_code}'")


# ---------------------------------------------------------------------------
# GET /api/dashboard/regions — list available regions (root only)
# ---------------------------------------------------------------------------

@router.get("/regions")
async def list_regions(current_user: CurrentActiveUser):
    """Return available regions for the region dropdown. Root admin only."""
    role = str(getattr(current_user, "role", "")).lower()
    if role != "root":
        raise HTTPException(status_code=403, detail="Region listing requires root role")

    if not _REGION_GATEWAY_URL:
        # No gateway configured — this deployment only knows about itself
        return [{"code": _REGION_CODE, "name": _REGION_CODE, "is_hub": True}]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_REGION_GATEWAY_URL}/api/regions")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("Failed to fetch regions from gateway: %s", e)
        # Fallback: return just the local region
        return [{"code": _REGION_CODE, "name": _REGION_CODE, "is_hub": True}]


class DashboardKpi(BaseModel):
    id: str
    label: str
    value: float | int
    unit: str | None = None


class DashboardSectionResponse(BaseModel):
    section: str
    kpis: list[DashboardKpi]


class TimeseriesPoint(BaseModel):
    date: str
    value: float | int


class PendingSeriesResponse(BaseModel):
    range: str
    series: list[TimeseriesPoint]


class HitlSeriesResponse(BaseModel):
    range: str
    series: list[TimeseriesPoint]


async def _resolve_super_admin_user_id(
    *,
    session: DbSession,
    org_id: UUID | None,
) -> UUID | None:
    if not org_id:
        return None
    stmt = (
        select(User)
        .join(UserOrganizationMembership, UserOrganizationMembership.user_id == User.id)
        .join(Role, Role.id == UserOrganizationMembership.role_id)
        .where(
            UserOrganizationMembership.org_id == org_id,
            UserOrganizationMembership.status == "active",
            func.lower(Role.name) == "super_admin",
        )
        .order_by(User.create_at.asc())
    )
    rows = (await session.exec(stmt)).all()
    return rows[0].id if rows else None


async def _designated_super_admin_org_ids(
    session: DbSession,
    current_user: CurrentActiveUser,
) -> set[UUID]:
    role = str(getattr(current_user, "role", "")).lower()
    if role != "super_admin":
        return set()
    rows = (
        await session.exec(
            select(UserOrganizationMembership.org_id).where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status == "active",
            )
        )
    ).all()
    org_ids = {r if isinstance(r, UUID) else r[0] for r in rows}
    if not org_ids:
        return set()
    allowed: set[UUID] = set()
    for org_id in org_ids:
        super_admin_id = await _resolve_super_admin_user_id(session=session, org_id=org_id)
        if super_admin_id == current_user.id:
            allowed.add(org_id)
    return allowed


async def _department_admin_dept_ids(
    session: DbSession,
    current_user: CurrentActiveUser,
) -> set[UUID]:
    role = str(getattr(current_user, "role", "")).lower()
    if role != "department_admin":
        return set()
    rows = (
        await session.exec(
            select(Department.id).where(Department.admin_user_id == current_user.id)
        )
    ).all()
    return {r if isinstance(r, UUID) else r[0] for r in rows}


@router.get("/sections/environment-lifecycle", response_model=DashboardSectionResponse, status_code=200)
async def get_lifecycle_kpis(
    *,
    request: Request,
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None = Query(default=None, description="Optional org filter for super admin"),
):
    # Cross-region proxy check
    proxied = await _maybe_proxy_to_region(request, current_user, "environment-lifecycle")
    if proxied is not None:
        return proxied

    role = str(getattr(current_user, "role", "")).lower()
    if role not in {"super_admin", "root"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    org_ids: set[UUID] | None = None
    if role == "super_admin":
        org_ids = await _designated_super_admin_org_ids(session, current_user)
        if org_id and org_id not in org_ids:
            raise HTTPException(status_code=403, detail="org_id not in your scope")
        if org_id:
            org_ids = {org_id}

    uat_filters = []
    uat_in_uat_filters = [AgentDeploymentUAT.moved_to_prod.is_(False)]
    uat_promoted_filters = [AgentDeploymentUAT.moved_to_prod.is_(True)]
    prod_filters = [AgentDeploymentProd.is_enabled.is_(False)]

    if org_ids is not None:
        if not org_ids:
            return DashboardSectionResponse(
                section="environment_lifecycle",
                kpis=[
                    DashboardKpi(id="agents_in_uat", label="Agents in UAT", value=0),
                    DashboardKpi(id="uat_to_prod_conversion_rate", label="UAT to PROD Conversion Rate", value=0, unit="%"),
                    DashboardKpi(id="deprecated_agent_count", label="Deprecated Agent Count", value=0),
                ],
            )
        uat_filters.append(AgentDeploymentUAT.org_id.in_(list(org_ids)))
        uat_in_uat_filters.append(AgentDeploymentUAT.org_id.in_(list(org_ids)))
        uat_promoted_filters.append(AgentDeploymentUAT.org_id.in_(list(org_ids)))
        prod_filters.append(AgentDeploymentProd.org_id.in_(list(org_ids)))

    uat_total = (
        await session.exec(select(func.count()).where(*uat_filters))
    ).one()
    uat_in_uat = (
        await session.exec(select(func.count()).where(*uat_in_uat_filters))
    ).one()
    uat_promoted = (
        await session.exec(select(func.count()).where(*uat_promoted_filters))
    ).one()
    deprecated_count = (
        await session.exec(select(func.count()).where(*prod_filters))
    ).one()

    total = int(uat_total or 0)
    in_uat = int(uat_in_uat or 0)
    promoted = int(uat_promoted or 0)
    conversion_rate = round((promoted / total) * 100, 2) if in_uat > 0 and total > 0 else 0

    return DashboardSectionResponse(
        section="environment_lifecycle",
        kpis=[
            DashboardKpi(id="agents_in_uat", label="Agents in UAT", value=in_uat),
            DashboardKpi(
                id="uat_to_prod_conversion_rate",
                label="UAT to PROD Conversion Rate",
                value=conversion_rate,
                unit="%",
            ),
            DashboardKpi(
                id="deprecated_agent_count",
                label="Deprecated Agent Count",
                value=int(deprecated_count or 0),
            ),
        ],
    )


@router.get("/sections/governance-guardrail", response_model=DashboardSectionResponse, status_code=200)
async def get_governance_guardrail_kpis(
    *,
    request: Request,
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None = Query(default=None, description="Optional org filter for super admin"),
):
    # Cross-region proxy check
    proxied = await _maybe_proxy_to_region(request, current_user, "governance-guardrail")
    if proxied is not None:
        return proxied

    role = str(getattr(current_user, "role", "")).lower()
    if role not in {"super_admin", "root"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    org_ids: set[UUID] | None = None
    if role == "super_admin":
        org_ids = await _designated_super_admin_org_ids(session, current_user)
        if org_id and org_id not in org_ids:
            raise HTTPException(status_code=403, detail="org_id not in your scope")
        if org_id:
            org_ids = {org_id}
    elif role == "root" and org_id:
        org_ids = {org_id}

    agent_scope_filters = []
    if org_ids is not None:
        if not org_ids:
            return DashboardSectionResponse(
                section="governance_guardrail",
                kpis=[
                    DashboardKpi(id="guardrail_violation_rate", label="Guardrail Violation Rate", value=0, unit="%"),
                    DashboardKpi(id="escalation_to_human_review", label="Escalation to Human Review", value=0),
                    DashboardKpi(id="agents_without_guardrails_pct", label="% Agents Without Guardrails", value=0, unit="%"),
                    DashboardKpi(id="policy_breach_attempts", label="Policy Breach Attempts", value=0),
                ],
            )
        agent_scope_filters.append(Agent.org_id.in_(list(org_ids)))

    # Escalation to Human Review: count HITL requests scoped to org via HITLRequest.org_id or Agent.org_id.
    hitl_stmt = (
        select(func.count())
        .select_from(HITLRequest)
        .join(Agent, Agent.id == HITLRequest.agent_id, isouter=True)
    )
    if org_ids is not None:
        hitl_stmt = hitl_stmt.where(func.coalesce(HITLRequest.org_id, Agent.org_id).in_(list(org_ids)))
    escalation_count = (await session.exec(hitl_stmt)).one()

    # % Agents Without Guardrails: total agents vs agents with guardrail bundle.
    total_agents_stmt = select(func.count(func.distinct(Agent.id))).where(Agent.deleted_at.is_(None))
    if agent_scope_filters:
        total_agents_stmt = total_agents_stmt.where(*agent_scope_filters)
    total_agents = (await session.exec(total_agents_stmt)).one()

    guardrail_stmt = (
        select(func.count(func.distinct(AgentBundle.agent_id)))
        .select_from(AgentBundle)
        .join(Agent, Agent.id == AgentBundle.agent_id, isouter=True)
        .where(AgentBundle.bundle_type == BundleTypeEnum.GUARDRAIL, Agent.deleted_at.is_(None))
    )
    if org_ids is not None:
        guardrail_stmt = guardrail_stmt.where(func.coalesce(AgentBundle.org_id, Agent.org_id).in_(list(org_ids)))
    guardrail_agents = (await session.exec(guardrail_stmt)).one()

    total = int(total_agents or 0)
    with_guardrails = int(guardrail_agents or 0)
    without_guardrails = max(total - with_guardrails, 0)
    without_pct = round((without_guardrails / total) * 100, 2) if total else 0

    # Guardrail Violation Rate: % of guardrail executions that blocked/masked/rewrote content.
    gel_total_stmt = select(func.count()).select_from(GuardrailExecutionLog)
    gel_violation_stmt = select(func.count()).select_from(GuardrailExecutionLog).where(
        GuardrailExecutionLog.is_violation.is_(True)
    )
    if org_ids is not None:
        gel_total_stmt = gel_total_stmt.where(GuardrailExecutionLog.org_id.in_(list(org_ids)))
        gel_violation_stmt = gel_violation_stmt.where(GuardrailExecutionLog.org_id.in_(list(org_ids)))
    total_executions = (await session.exec(gel_total_stmt)).one()
    total_violations = (await session.exec(gel_violation_stmt)).one()
    violation_rate = round((int(total_violations or 0) / int(total_executions or 1)) * 100, 2) if total_executions else 0

    # Policy Breach Attempts: violations from prompt-injection / jailbreak guardrails only.
    # Step 1: Get IDs of guardrails with matching categories
    breach_category_stmt = select(
        cast(GuardrailCatalogue.id, String)
    ).where(
        GuardrailCatalogue.category.in_(["prompt-injection", "jailbreak"])
    )
    breach_guardrail_ids = list((await session.exec(breach_category_stmt)).all())

    # Step 2: Count violations matching those guardrail IDs
    breach_count = 0
    if breach_guardrail_ids:
        breach_violation_stmt = (
            select(func.count())
            .select_from(GuardrailExecutionLog)
            .where(
                GuardrailExecutionLog.is_violation.is_(True),
                GuardrailExecutionLog.guardrail_id.in_(breach_guardrail_ids),
            )
        )
        if org_ids is not None:
            breach_violation_stmt = breach_violation_stmt.where(
                GuardrailExecutionLog.org_id.in_(list(org_ids))
            )
        breach_count = (await session.exec(breach_violation_stmt)).one()

    return DashboardSectionResponse(
        section="governance_guardrail",
        kpis=[
            DashboardKpi(
                id="guardrail_violation_rate",
                label="Guardrail Violation Rate",
                value=violation_rate,
                unit="%",
            ),
            DashboardKpi(
                id="escalation_to_human_review",
                label="Escalation to Human Review",
                value=int(escalation_count or 0),
            ),
            DashboardKpi(
                id="agents_without_guardrails_pct",
                label="% Agents Without Guardrails",
                value=without_pct,
                unit="%",
            ),
            DashboardKpi(
                id="policy_breach_attempts",
                label="Policy Breach Attempts",
                value=int(breach_count or 0),
            ),
        ],
    )


@router.get("/sections/department-usage", response_model=DashboardSectionResponse, status_code=200)
async def get_department_usage_kpis(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "department_admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    dept_ids = await _department_admin_dept_ids(session, current_user)
    if not dept_ids:
        return DashboardSectionResponse(
            section="department_usage",
            kpis=[
                DashboardKpi(id="active_agents_dept_uat", label="Active Agents in Dept (UAT)", value=0),
                DashboardKpi(id="active_agents_dept_prod", label="Active Agents in Dept (PROD)", value=0),
            ],
        )

    assigned_agent_ids = select(AgentPublishRecipient.agent_id).where(
        AgentPublishRecipient.dept_id.in_(list(dept_ids))
    )

    # If a UAT deployment has a pending promotion to PROD, we still count it as active in UAT
    # (department admins treat pending approvals as still part of the active UAT footprint).
    pending_promotion_uat_ids = (
        select(AgentDeploymentProd.promoted_from_uat_id)
        .where(
            AgentDeploymentProd.promoted_from_uat_id.is_not(None),
            AgentDeploymentProd.status == "PENDING_APPROVAL",
        )
    )

    uat_active = (
        await session.exec(
            select(func.count())
            .where(
                or_(
                    AgentDeploymentUAT.dept_id.in_(list(dept_ids)),
                    AgentDeploymentUAT.agent_id.in_(assigned_agent_ids),
                ),
                AgentDeploymentUAT.is_active.is_(True),
                or_(
                    AgentDeploymentUAT.moved_to_prod.is_(False),
                    AgentDeploymentUAT.id.in_(pending_promotion_uat_ids),
                ),
            )
        )
    ).one()
    prod_active = (
        await session.exec(
            select(func.count())
            .where(
                or_(
                    AgentDeploymentProd.dept_id.in_(list(dept_ids)),
                    AgentDeploymentProd.agent_id.in_(assigned_agent_ids),
                ),
                AgentDeploymentProd.is_active.is_(True),
            )
        )
    ).one()

    return DashboardSectionResponse(
        section="department_usage",
        kpis=[
            DashboardKpi(
                id="active_agents_dept_uat",
                label="Active Agents in Dept (UAT)",
                value=int(uat_active or 0),
            ),
            DashboardKpi(
                id="active_agents_dept_prod",
                label="Active Agents in Dept (PROD)",
                value=int(prod_active or 0),
            ),
        ],
    )


@router.get("/sections/department-approval", response_model=DashboardSectionResponse, status_code=200)
async def get_department_approval_kpis(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "department_admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    dept_ids = await _department_admin_dept_ids(session, current_user)
    if not dept_ids:
        return DashboardSectionResponse(
            section="department_approval",
            kpis=[
                DashboardKpi(id="pending_approvals", label="Pending Approvals", value=0),
                DashboardKpi(id="rejection_rate", label="Rejection Rate", value=0, unit="%"),
                DashboardKpi(id="avg_approval_time", label="Avg Approval Time", value=0, unit="min"),
            ],
        )

    assigned_agent_ids = select(AgentPublishRecipient.agent_id).where(
        AgentPublishRecipient.dept_id.in_(list(dept_ids))
    )

    pending_count = (
        await session.exec(
            select(func.count())
            .where(
                ApprovalRequest.decision.is_(None),
                or_(
                    ApprovalRequest.dept_id.in_(list(dept_ids)),
                    ApprovalRequest.agent_id.in_(assigned_agent_ids),
                ),
            )
        )
    ).one()
    decided_count = (
        await session.exec(
            select(func.count())
            .where(
                ApprovalRequest.decision.is_not(None),
                or_(
                    ApprovalRequest.dept_id.in_(list(dept_ids)),
                    ApprovalRequest.agent_id.in_(assigned_agent_ids),
                ),
            )
        )
    ).one()
    rejected_count = (
        await session.exec(
            select(func.count())
            .where(
                ApprovalRequest.decision == "REJECTED",
                or_(
                    ApprovalRequest.dept_id.in_(list(dept_ids)),
                    ApprovalRequest.agent_id.in_(assigned_agent_ids),
                ),
            )
        )
    ).one()
    avg_seconds = (
        await session.exec(
            select(
                func.avg(
                    func.extract(
                        "epoch",
                        ApprovalRequest.reviewed_at - ApprovalRequest.requested_at,
                    )
                )
            )
            .where(
                ApprovalRequest.reviewed_at.is_not(None),
                or_(
                    ApprovalRequest.dept_id.in_(list(dept_ids)),
                    ApprovalRequest.agent_id.in_(assigned_agent_ids),
                ),
            )
        )
    ).one()
    decided = int(decided_count or 0)
    rejected = int(rejected_count or 0)
    rejection_rate = round((rejected / decided) * 100, 2) if decided else 0
    avg_minutes = round((float(avg_seconds) / 60), 2) if avg_seconds is not None else 0

    return DashboardSectionResponse(
        section="department_approval",
        kpis=[
            DashboardKpi(
                id="pending_approvals",
                label="Pending Approvals",
                value=int(pending_count or 0),
            ),
            DashboardKpi(
                id="rejection_rate",
                label="Rejection Rate",
                value=rejection_rate,
                unit="%",
            ),
            DashboardKpi(
                id="avg_approval_time",
                label="Avg Approval Time",
                value=avg_minutes,
                unit="min",
            ),
        ],
    )


def _range_to_days(range_key: str) -> int:
    if range_key == "7d":
        return 7
    if range_key == "30d":
        return 30
    if range_key == "12w":
        return 84
    raise HTTPException(status_code=400, detail="Unsupported range")


def _coerce_tz_offset_minutes(tz_offset_minutes: int | None) -> int:
    if tz_offset_minutes is None:
        return 0
    if tz_offset_minutes > 840:
        return 840
    if tz_offset_minutes < -840:
        return -840
    return int(tz_offset_minutes)


def _apply_tz_offset(dt: datetime, tz_offset_minutes: int) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt + timedelta(minutes=tz_offset_minutes)


def _normalize_day(value: date | datetime | str, tz_offset_minutes: int) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return _apply_tz_offset(value, tz_offset_minutes).date()
    parsed = datetime.fromisoformat(str(value))
    return _apply_tz_offset(parsed, tz_offset_minutes).date()


def _local_range_window(days: int, tz_offset_minutes: int) -> tuple[date, datetime, datetime]:
    now_utc = datetime.now(timezone.utc)
    local_now = _apply_tz_offset(now_utc, tz_offset_minutes)
    today_local = local_now.date()
    start_day = today_local - timedelta(days=days - 1)
    # Convert local day bounds back to UTC naive for DB comparisons.
    start_dt = (datetime.combine(start_day, time.min) - timedelta(minutes=tz_offset_minutes)).replace(tzinfo=None)
    end_dt = (datetime.combine(today_local + timedelta(days=1), time.min) - timedelta(minutes=tz_offset_minutes)).replace(tzinfo=None)
    return start_day, start_dt, end_dt


@router.get("/sections/department-approval/pending-series", response_model=PendingSeriesResponse, status_code=200)
async def get_department_approval_pending_series(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    range_key: str = Query(default="7d", alias="range"),
    tz_offset_minutes: int | None = Query(default=None),
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "department_admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    dept_ids = await _department_admin_dept_ids(session, current_user)
    days = _range_to_days(range_key)
    tz_minutes = _coerce_tz_offset_minutes(tz_offset_minutes)
    start_day, start_dt, end_dt = _local_range_window(days, tz_minutes)

    if not dept_ids:
        series = [
            TimeseriesPoint(date=(start_day + timedelta(days=i)).isoformat(), value=0)
            for i in range(days)
        ]
        return PendingSeriesResponse(range=range_key, series=series)

    assigned_agent_ids = select(AgentPublishRecipient.agent_id).where(
        AgentPublishRecipient.dept_id.in_(list(dept_ids))
    )
    current_pending = (
        await session.exec(
            select(func.count())
            .where(
                ApprovalRequest.decision.is_(None),
                or_(
                    ApprovalRequest.dept_id.in_(list(dept_ids)),
                    ApprovalRequest.agent_id.in_(assigned_agent_ids),
                ),
            )
        )
    ).one()
    baseline_pending = (
        await session.exec(
            select(func.count())
            .where(
                or_(
                    ApprovalRequest.dept_id.in_(list(dept_ids)),
                    ApprovalRequest.agent_id.in_(assigned_agent_ids),
                ),
                ApprovalRequest.requested_at < start_dt,
                (
                    ApprovalRequest.decision.is_(None)
                    | (ApprovalRequest.reviewed_at.is_not(None) & (ApprovalRequest.reviewed_at >= start_dt))
                ),
            )
        )
    ).one()

    created_rows = (
        await session.exec(
            select(ApprovalRequest.requested_at)
            .where(
                or_(
                    ApprovalRequest.dept_id.in_(list(dept_ids)),
                    ApprovalRequest.agent_id.in_(assigned_agent_ids),
                ),
                ApprovalRequest.requested_at >= start_dt,
                ApprovalRequest.requested_at < end_dt,
            )
        )
    ).all()
    decided_rows = (
        await session.exec(
            select(ApprovalRequest.reviewed_at)
            .where(
                ApprovalRequest.decision.is_not(None),
                ApprovalRequest.reviewed_at.is_not(None),
                or_(
                    ApprovalRequest.dept_id.in_(list(dept_ids)),
                    ApprovalRequest.agent_id.in_(assigned_agent_ids),
                ),
                ApprovalRequest.reviewed_at >= start_dt,
                ApprovalRequest.reviewed_at < end_dt,
            )
        )
    ).all()

    created_by_day: dict[date, int] = {}
    for row in created_rows:
        value = row[0] if isinstance(row, (list, tuple)) else row
        day = _normalize_day(value, tz_minutes)
        created_by_day[day] = created_by_day.get(day, 0) + 1

    decided_by_day: dict[date, int] = {}
    for row in decided_rows:
        value = row[0] if isinstance(row, (list, tuple)) else row
        day = _normalize_day(value, tz_minutes)
        decided_by_day[day] = decided_by_day.get(day, 0) + 1

    pending = int(baseline_pending or 0)
    series: list[TimeseriesPoint] = []
    for i in range(days):
        day = start_day + timedelta(days=i)
        pending += created_by_day.get(day, 0) - decided_by_day.get(day, 0)
        if pending < 0:
            pending = 0
        series.append(TimeseriesPoint(date=day.isoformat(), value=pending))

    if series:
        series[-1] = TimeseriesPoint(
            date=series[-1].date,
            value=int(current_pending or 0),
        )

    return PendingSeriesResponse(range=range_key, series=series)


@router.get("/sections/department-hitl", response_model=DashboardSectionResponse, status_code=200)
async def get_department_hitl_kpis(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "department_admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    dept_ids = await _department_admin_dept_ids(session, current_user)
    if not dept_ids:
        return DashboardSectionResponse(
            section="department_hitl",
            kpis=[
                DashboardKpi(id="hitl_enabled_agents", label="Agents with HITL", value=0),
                DashboardKpi(id="hitl_invocation_rate", label="HITL Invocation Rate", value=0, unit="%"),
                DashboardKpi(id="avg_hitl_response_time", label="Avg HITL Response Time", value=0, unit="min"),
            ],
        )

    assigned_agent_ids = select(AgentPublishRecipient.agent_id).where(
        AgentPublishRecipient.dept_id.in_(list(dept_ids))
    )
    total_agents = (
        await session.exec(
            select(func.count(func.distinct(Agent.id))).where(
                or_(
                    Agent.dept_id.in_(list(dept_ids)),
                    Agent.id.in_(assigned_agent_ids),
                ),
                Agent.deleted_at.is_(None),
            )
        )
    ).one()
    hitl_total = (
        await session.exec(
            select(func.count())
            .where(
                or_(
                    HITLRequest.dept_id.in_(list(dept_ids)),
                    HITLRequest.agent_id.in_(assigned_agent_ids),
                )
            )
        )
    ).one()
    hitl_enabled_agents = (
        await session.exec(
            select(func.count(func.distinct(AgentBundle.agent_id)))
            .select_from(AgentBundle)
            .join(Agent, Agent.id == AgentBundle.agent_id, isouter=True)
            .where(
                AgentBundle.bundle_type == BundleTypeEnum.TOOL,
                AgentBundle.resource_name == "Human Approval",
                or_(
                    AgentBundle.dept_id.in_(list(dept_ids)),
                    Agent.dept_id.in_(list(dept_ids)),
                    AgentBundle.agent_id.in_(assigned_agent_ids),
                    Agent.id.in_(assigned_agent_ids),
                ),
                Agent.deleted_at.is_(None),
            )
        )
    ).one()

    decided_rows = (
        await session.exec(
            select(HITLRequest.requested_at, HITLRequest.decided_at)
            .where(
                or_(
                    HITLRequest.dept_id.in_(list(dept_ids)),
                    HITLRequest.agent_id.in_(assigned_agent_ids),
                ),
                HITLRequest.decided_at.is_not(None),
            )
        )
    ).all()

    total_agents_count = int(total_agents or 0)
    hitl_total_count = int(hitl_total or 0)
    hitl_enabled_count = int(hitl_enabled_agents or 0)
    invocation_rate = int(round((hitl_total_count / total_agents_count) * 100)) if total_agents_count else 0

    total_minutes = 0.0
    decided_count = 0
    for row in decided_rows:
        requested_at = row[0] if isinstance(row, (list, tuple)) else row.requested_at
        decided_at = row[1] if isinstance(row, (list, tuple)) else row.decided_at
        if not requested_at or not decided_at:
            continue
        delta = decided_at - requested_at
        total_minutes += max(delta.total_seconds(), 0) / 60.0
        decided_count += 1
    avg_minutes = round((total_minutes / decided_count), 1) if decided_count else 0

    return DashboardSectionResponse(
        section="department_hitl",
        kpis=[
            DashboardKpi(
                id="hitl_enabled_agents",
                label="Agents with HITL",
                value=hitl_enabled_count,
            ),
            DashboardKpi(
                id="hitl_invocation_rate",
                label="HITL Invocation Rate",
                value=invocation_rate,
                unit="%",
            ),
            DashboardKpi(
                id="avg_hitl_response_time",
                label="Avg HITL Response Time",
                value=avg_minutes,
                unit="min",
            ),
        ],
    )


@router.get("/sections/department-hitl/invocation-series", response_model=HitlSeriesResponse, status_code=200)
async def get_department_hitl_invocation_series(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    range_key: str = Query(default="7d", alias="range"),
    tz_offset_minutes: int | None = Query(default=None),
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "department_admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    dept_ids = await _department_admin_dept_ids(session, current_user)
    days = _range_to_days(range_key)
    tz_minutes = _coerce_tz_offset_minutes(tz_offset_minutes)
    start_day, start_dt, end_dt = _local_range_window(days, tz_minutes)

    if not dept_ids:
        series = [
            TimeseriesPoint(date=(start_day + timedelta(days=i)).isoformat(), value=0)
            for i in range(days)
        ]
        return HitlSeriesResponse(range=range_key, series=series)

    assigned_agent_ids = select(AgentPublishRecipient.agent_id).where(
        AgentPublishRecipient.dept_id.in_(list(dept_ids))
    )
    total_agents = (
        await session.exec(
            select(func.count(func.distinct(Agent.id))).where(
                or_(
                    Agent.dept_id.in_(list(dept_ids)),
                    Agent.id.in_(assigned_agent_ids),
                ),
                Agent.deleted_at.is_(None),
            )
        )
    ).one()
    total_agents_count = int(total_agents or 0)

    rows = (
        await session.exec(
            select(HITLRequest.requested_at)
            .where(
                or_(
                    HITLRequest.dept_id.in_(list(dept_ids)),
                    HITLRequest.agent_id.in_(assigned_agent_ids),
                ),
                HITLRequest.requested_at >= start_dt,
                HITLRequest.requested_at < end_dt,
            )
        )
    ).all()
    counts_by_day: dict[date, int] = {}
    for row in rows:
        value = row[0] if isinstance(row, (list, tuple)) else row
        day = _normalize_day(value, tz_minutes)
        counts_by_day[day] = counts_by_day.get(day, 0) + 1

    series: list[TimeseriesPoint] = []
    for i in range(days):
        day = start_day + timedelta(days=i)
        count = counts_by_day.get(day, 0)
        rate = int(round((count / total_agents_count) * 100)) if total_agents_count else 0
        series.append(TimeseriesPoint(date=day.isoformat(), value=rate))

    return HitlSeriesResponse(range=range_key, series=series)


@router.get("/sections/department-hitl/response-time-series", response_model=HitlSeriesResponse, status_code=200)
async def get_department_hitl_response_time_series(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    range_key: str = Query(default="7d", alias="range"),
    tz_offset_minutes: int | None = Query(default=None),
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "department_admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    dept_ids = await _department_admin_dept_ids(session, current_user)
    days = _range_to_days(range_key)
    tz_minutes = _coerce_tz_offset_minutes(tz_offset_minutes)
    start_day, start_dt, end_dt = _local_range_window(days, tz_minutes)

    if not dept_ids:
        series = [
            TimeseriesPoint(date=(start_day + timedelta(days=i)).isoformat(), value=0)
            for i in range(days)
        ]
        return HitlSeriesResponse(range=range_key, series=series)

    assigned_agent_ids = select(AgentPublishRecipient.agent_id).where(
        AgentPublishRecipient.dept_id.in_(list(dept_ids))
    )
    rows = (
        await session.exec(
            select(HITLRequest.requested_at, HITLRequest.decided_at)
            .where(
                or_(
                    HITLRequest.dept_id.in_(list(dept_ids)),
                    HITLRequest.agent_id.in_(assigned_agent_ids),
                ),
                HITLRequest.decided_at.is_not(None),
                HITLRequest.requested_at >= start_dt,
                HITLRequest.requested_at < end_dt,
            )
        )
    ).all()

    totals: dict[date, float] = {}
    counts: dict[date, int] = {}
    for row in rows:
        requested_at = row[0] if isinstance(row, (list, tuple)) else row.requested_at
        decided_at = row[1] if isinstance(row, (list, tuple)) else row.decided_at
        if not requested_at or not decided_at:
            continue
        day = _normalize_day(requested_at, tz_minutes)
        delta = decided_at - requested_at
        minutes = max(delta.total_seconds(), 0) / 60.0
        totals[day] = totals.get(day, 0.0) + minutes
        counts[day] = counts.get(day, 0) + 1

    series: list[TimeseriesPoint] = []
    for i in range(days):
        day = start_day + timedelta(days=i)
        if counts.get(day, 0) == 0:
            series.append(TimeseriesPoint(date=day.isoformat(), value=0))
        else:
            avg = totals[day] / counts[day]
            series.append(TimeseriesPoint(date=day.isoformat(), value=round(avg, 1)))

    return HitlSeriesResponse(range=range_key, series=series)


@router.get("/sections/developer-code", response_model=DashboardSectionResponse, status_code=200)
async def get_developer_code_kpis(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "developer":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    rows = (
        await session.exec(
            select(Agent.id, func.count(func.distinct(AgentDeploymentUAT.version_number)))
            .select_from(Agent)
            .join(AgentDeploymentUAT, AgentDeploymentUAT.agent_id == Agent.id, isouter=True)
            .where(
                Agent.user_id == current_user.id,
                Agent.deleted_at.is_(None),
            )
            .group_by(Agent.id)
        )
    ).all()
    if not rows:
        avg_versions = 0
    else:
        counts = [int(row[1] or 0) if isinstance(row, (list, tuple)) else int(row[1]) for row in rows]
        avg_versions = int(round(sum(counts) / len(counts))) if counts else 0

    return DashboardSectionResponse(
        section="developer_code",
        kpis=[
            DashboardKpi(
                id="version_count_per_agent",
                label="Avg. Version Count of Agents",
                value=avg_versions,
            ),
        ],
    )


@router.get("/sections/business-maturity", response_model=DashboardSectionResponse, status_code=200)
async def get_business_maturity_kpis(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "business_user":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    total_agents = (
        await session.exec(
            select(func.count(func.distinct(Agent.id))).where(
                Agent.user_id == current_user.id,
                Agent.deleted_at.is_(None),
            )
        )
    ).one()
    total_agents_count = int(total_agents or 0)

    guardrail_agents = (
        await session.exec(
            select(func.count(func.distinct(AgentBundle.agent_id)))
            .select_from(AgentBundle)
            .join(Agent, Agent.id == AgentBundle.agent_id, isouter=True)
            .where(
                Agent.user_id == current_user.id,
                AgentBundle.bundle_type == BundleTypeEnum.GUARDRAIL,
            )
        )
    ).one()
    guardrail_count = int(guardrail_agents or 0)
    guardrail_pct = int(round((guardrail_count / total_agents_count) * 100)) if total_agents_count else 0

    rag_agents = (
        await session.exec(
            select(func.count(func.distinct(AgentBundle.agent_id)))
            .select_from(AgentBundle)
            .join(Agent, Agent.id == AgentBundle.agent_id, isouter=True)
            .where(
                Agent.user_id == current_user.id,
                AgentBundle.bundle_type.in_([BundleTypeEnum.VECTOR_DB, BundleTypeEnum.KNOWLEDGE_BASE]),
            )
        )
    ).one()
    rag_count = int(rag_agents or 0)
    rag_pct = int(round((rag_count / total_agents_count) * 100)) if total_agents_count else 0

    hitl_agents = (
        await session.exec(
            select(func.count(func.distinct(AgentBundle.agent_id)))
            .select_from(AgentBundle)
            .join(Agent, Agent.id == AgentBundle.agent_id, isouter=True)
            .where(
                Agent.user_id == current_user.id,
                AgentBundle.bundle_type == BundleTypeEnum.TOOL,
                AgentBundle.resource_name == "Human Approval",
            )
        )
    ).one()
    hitl_count = int(hitl_agents or 0)
    hitl_pct = int(round((hitl_count / total_agents_count) * 100)) if total_agents_count else 0

    return DashboardSectionResponse(
        section="business_maturity",
        kpis=[
            DashboardKpi(id="agents_with_guardrails_pct", label="% Agents with Guardrails", value=guardrail_pct, unit="%"),
            DashboardKpi(id="agents_with_rag_pct", label="% Agents with RAG", value=rag_pct, unit="%"),
            DashboardKpi(id="agents_with_hitl_pct", label="% Agents with HITL", value=hitl_pct, unit="%"),
        ],
    )


@router.get("/sections/business-experience", response_model=DashboardSectionResponse, status_code=200)
async def get_business_experience_kpis(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    role = str(getattr(current_user, "role", "")).lower()
    if role != "business_user":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    assigned_agent_ids = select(AgentPublishRecipient.agent_id).where(
        AgentPublishRecipient.recipient_user_id == current_user.id
    )
    user_sessions = (
        select(func.distinct(OrchConversationTable.session_id).label("session_id"))
        .where(
            or_(
                OrchConversationTable.user_id == current_user.id,
                OrchConversationTable.agent_id.in_(assigned_agent_ids),
            ),
            OrchConversationTable.session_id.is_not(None),
        )
        .subquery()
    )
    total_messages = (
        await session.exec(
            select(func.count())
            .select_from(OrchConversationTable)
            .where(
                OrchConversationTable.session_id.is_not(None),
                OrchConversationTable.session_id.in_(select(user_sessions.c.session_id)),
            )
        )
    ).one()
    total_messages_count = int(total_messages or 0)

    hitl_requests = (
        await session.exec(
            select(func.count()).where(
                HITLRequest.session_id.is_not(None),
                HITLRequest.session_id.in_(select(user_sessions.c.session_id)),
            )
        )
    ).one()
    hitl_requests_count = int(hitl_requests or 0)
    escalation_pct = round((hitl_requests_count / total_messages_count) * 100, 2) if total_messages_count else 0

    avg_rating = (
        await session.exec(
            select(func.avg(AgentRegistryRating.score))
        )
    ).one()
    avg_rating_value = round(float(avg_rating), 2) if avg_rating is not None else 0

    return DashboardSectionResponse(
        section="business_experience",
        kpis=[
            DashboardKpi(
                id="escalation_to_human",
                label="Escalation to Human",
                value=escalation_pct,
                unit="%",
            ),
            DashboardKpi(
                id="user_satisfaction_score",
                label="User Satisfaction Score",
                value=avg_rating_value,
                unit="/5",
            ),
        ],
    )


@router.get("/sections/root-maturity", response_model=DashboardSectionResponse, status_code=200)
async def get_root_maturity_kpis(
    *,
    request: Request,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    # Cross-region proxy check
    proxied = await _maybe_proxy_to_region(request, current_user, "root-maturity")
    if proxied is not None:
        return proxied

    role = str(getattr(current_user, "role", "")).lower()
    if role not in {"root", "leader_executive"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    total_agents = (
        await session.exec(
            select(func.count(func.distinct(Agent.id))).where(
                Agent.deleted_at.is_(None),
            )
        )
    ).one()
    total_agents_count = int(total_agents or 0)

    guardrail_agents = (
        await session.exec(
            select(func.count(func.distinct(AgentBundle.agent_id)))
            .select_from(AgentBundle)
            .where(
                AgentBundle.bundle_type == BundleTypeEnum.GUARDRAIL,
            )
        )
    ).one()
    guardrail_count = int(guardrail_agents or 0)
    guardrail_pct = int(round((guardrail_count / total_agents_count) * 100)) if total_agents_count else 0

    rag_agents = (
        await session.exec(
            select(func.count(func.distinct(AgentBundle.agent_id)))
            .select_from(AgentBundle)
            .where(
                AgentBundle.bundle_type.in_([BundleTypeEnum.VECTOR_DB, BundleTypeEnum.KNOWLEDGE_BASE]),
            )
        )
    ).one()
    rag_count = int(rag_agents or 0)
    rag_pct = int(round((rag_count / total_agents_count) * 100)) if total_agents_count else 0

    hitl_agents = (
        await session.exec(
            select(func.count(func.distinct(AgentBundle.agent_id)))
            .select_from(AgentBundle)
            .where(
                AgentBundle.bundle_type == BundleTypeEnum.TOOL,
                AgentBundle.resource_name == "Human Approval",
            )
        )
    ).one()
    hitl_count = int(hitl_agents or 0)
    hitl_pct = int(round((hitl_count / total_agents_count) * 100)) if total_agents_count else 0

    return DashboardSectionResponse(
        section="root_maturity",
        kpis=[
            DashboardKpi(id="agents_with_guardrails_pct", label="% Agents with Guardrails", value=guardrail_pct, unit="%"),
            DashboardKpi(id="agents_with_rag_pct", label="% Agents with RAG", value=rag_pct, unit="%"),
            DashboardKpi(id="agents_with_hitl_pct", label="% Agents with HITL", value=hitl_pct, unit="%"),
        ],
    )


# ---------------------------------------------------------------------------
# Observability-based KPIs (super_admin / root)
# ---------------------------------------------------------------------------

class CostTrendResponse(BaseModel):
    range: str
    series: list[TimeseriesPoint]


# Process-level cache + lock so concurrent dashboard requests share one fetch.
_dashboard_trace_cache: dict[str, tuple[float, list]] = {}
_dashboard_trace_lock = asyncio.Lock()
_DASHBOARD_TRACE_TTL = 60.0  # seconds


async def _fetch_observability_traces(
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None,
    from_days: int = 30,
):
    """Fetch traces for dashboard KPIs with dedup cache.

    Multiple dashboard endpoints call this concurrently on page load.
    The lock ensures only ONE Langfuse fetch happens; others wait and
    reuse the cached result.

    TraceStore.get_traces() is SYNCHRONOUS (HTTP calls + thread-pool
    enrichment) so it MUST run in asyncio.to_thread() to avoid blocking
    the event loop — otherwise every other request (including non-dashboard)
    hangs until the Langfuse fetch completes.
    """
    cache_key = f"{current_user.id}:{org_id}:{from_days}"

    # Fast path: return cached result without lock
    cached = _dashboard_trace_cache.get(cache_key)
    if cached and (_time.monotonic() - cached[0]) < _DASHBOARD_TRACE_TTL:
        return cached[1]

    async with _dashboard_trace_lock:
        # Re-check after acquiring lock (another request may have filled cache)
        cached = _dashboard_trace_cache.get(cache_key)
        if cached and (_time.monotonic() - cached[0]) < _DASHBOARD_TRACE_TTL:
            return cached[1]

        from agentcore.api.observability.scope import resolve_scope_context
        from agentcore.api.observability.trace_store import TraceStore
        from agentcore.api.observability.parsing import compute_date_range, clear_request_caches

        clear_request_caches()

        allowed_user_ids, scoped_clients, scope_key, _ = await resolve_scope_context(
            session=session,
            current_user=current_user,
            org_id=org_id,
            trace_scope="all",
            enforce_filter_for_admin=False,
        )
        if not scoped_clients or not allowed_user_ids:
            return []

        from_ts, to_ts = compute_date_range(None, None, None, default_days=from_days)

        # Run the SYNCHRONOUS Langfuse fetch in a thread pool so the
        # event loop stays free to serve other requests.
        traces, _ = await asyncio.to_thread(
            TraceStore.get_traces,
            clients=scoped_clients,
            allowed_user_ids=allowed_user_ids,
            scope_key=scope_key,
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            fetch_all=False,
            limit=500,
        )

        _dashboard_trace_cache[cache_key] = (_time.monotonic(), traces)

        # Evict stale entries
        now = _time.monotonic()
        stale = [k for k, v in _dashboard_trace_cache.items() if (now - v[0]) > _DASHBOARD_TRACE_TTL * 2]
        for k in stale:
            _dashboard_trace_cache.pop(k, None)

        return traces


@router.get("/sections/observability-health", response_model=DashboardSectionResponse, status_code=200)
async def get_observability_health_kpis(
    *,
    request: Request,
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None = Query(default=None, description="Optional org filter for super admin"),
):
    """Platform Health KPIs: total agent runs, failed runs, failure rate."""
    proxied = await _maybe_proxy_to_region(request, current_user, "observability-health")
    if proxied is not None:
        return proxied

    role = str(getattr(current_user, "role", "")).lower()
    if role not in {"super_admin", "root"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if role == "super_admin":
        org_ids = await _designated_super_admin_org_ids(session, current_user)
        if org_id and org_id not in org_ids:
            raise HTTPException(status_code=403, detail="org_id not in your scope")

    try:
        traces = await _fetch_observability_traces(session, current_user, org_id)
    except Exception as e:
        logger.warning("Failed to fetch observability traces for dashboard: %s", e)
        traces = []

    total = len(traces)
    failed = sum(
        1 for t in traces
        if (getattr(t, "error_count", 0) or 0) > 0
        or str(getattr(t, "level", "") or "").upper() == "ERROR"
    )
    failure_rate = round((failed / total) * 100, 2) if total > 0 else 0

    return DashboardSectionResponse(
        section="observability_health",
        kpis=[
            DashboardKpi(id="total_agent_runs", label="Total Runs", value=total),
            DashboardKpi(id="failed_agent_runs", label="Total Failed Runs", value=failed),
            DashboardKpi(id="execution_failure_rate", label="Execution Failure Rate", value=failure_rate, unit="%"),
        ],
    )


@router.get("/sections/cost-financial", response_model=DashboardSectionResponse, status_code=200)
async def get_cost_financial_kpis(
    *,
    request: Request,
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None = Query(default=None, description="Optional org filter for super admin"),
):
    """Cost KPIs: average cost per agent run."""
    proxied = await _maybe_proxy_to_region(request, current_user, "cost-financial")
    if proxied is not None:
        return proxied

    role = str(getattr(current_user, "role", "")).lower()
    if role not in {"super_admin", "root"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if role == "super_admin":
        org_ids = await _designated_super_admin_org_ids(session, current_user)
        if org_id and org_id not in org_ids:
            raise HTTPException(status_code=403, detail="org_id not in your scope")

    try:
        traces = await _fetch_observability_traces(session, current_user, org_id)
    except Exception as e:
        logger.warning("Failed to fetch observability traces for cost dashboard: %s", e)
        traces = []

    total = len(traces)
    total_cost = sum(getattr(t, "total_cost", 0) or 0 for t in traces)
    avg_cost = round(total_cost / total, 4) if total > 0 else 0

    return DashboardSectionResponse(
        section="cost_financial",
        kpis=[
            DashboardKpi(id="total_cost", label="Total Cost", value=round(total_cost, 4), unit="$"),
            DashboardKpi(id="avg_cost_per_run", label="Avg Cost Per Run", value=avg_cost, unit="$"),
        ],
    )


@router.get("/sections/cost-financial/monthly-trend", response_model=CostTrendResponse, status_code=200)
async def get_cost_monthly_trend(
    *,
    request: Request,
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None = Query(default=None, description="Optional org filter for super admin"),
    range: str = Query(default="30d", description="'30d' or '90d'"),
    tz_offset_minutes: int | None = Query(default=None, description="Client TZ offset in minutes"),
):
    """Monthly cost trend: daily cost values for charting."""
    proxied = await _maybe_proxy_to_region(request, current_user, "cost-financial/monthly-trend")
    if proxied is not None:
        return proxied

    role = str(getattr(current_user, "role", "")).lower()
    if role not in {"super_admin", "root"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if role == "super_admin":
        org_ids = await _designated_super_admin_org_ids(session, current_user)
        if org_id and org_id not in org_ids:
            raise HTTPException(status_code=403, detail="org_id not in your scope")

    days = 90 if range == "90d" else 30
    tz_off = _coerce_tz_offset_minutes(tz_offset_minutes)

    try:
        traces = await _fetch_observability_traces(session, current_user, org_id, from_days=days)
    except Exception as e:
        logger.warning("Failed to fetch observability traces for cost trend: %s", e)
        traces = []

    daily_cost: dict[str, float] = {}
    for t in traces:
        ts = getattr(t, "timestamp", None)
        if not ts:
            continue
        if tz_off is not None:
            local_ts = ts + timedelta(minutes=tz_off)
            date_str = local_ts.strftime("%Y-%m-%d")
        else:
            date_str = ts.strftime("%Y-%m-%d")
        daily_cost[date_str] = daily_cost.get(date_str, 0) + (getattr(t, "total_cost", 0) or 0)

    series = [
        TimeseriesPoint(date=d, value=round(v, 4))
        for d, v in sorted(daily_cost.items())
    ]

    return CostTrendResponse(range=range, series=series)


@router.get("/sections/cost-p95-trend", response_model=CostTrendResponse, status_code=200)
async def get_cost_p95_trend(
    *,
    request: Request,
    session: DbSession,
    current_user: CurrentActiveUser,
    org_id: UUID | None = Query(default=None, description="Optional org filter"),
    range: str = Query(default="30d", description="'30d' or '90d'"),
    tz_offset_minutes: int | None = Query(default=None, description="Client TZ offset in minutes"),
):
    """Cost P95 trend: daily P95 cost per trace for charting (leader executive)."""
    proxied = await _maybe_proxy_to_region(request, current_user, "cost-p95-trend")
    if proxied is not None:
        return proxied

    role = str(getattr(current_user, "role", "")).lower()
    if role != "leader_executive":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    days = 90 if range == "90d" else 30
    tz_off = _coerce_tz_offset_minutes(tz_offset_minutes)

    try:
        traces = await _fetch_observability_traces(session, current_user, org_id, from_days=days)
    except Exception as e:
        logger.warning("Failed to fetch traces for cost P95 trend: %s", e)
        traces = []

    # Bucket costs by date
    daily_costs: dict[str, list[float]] = {}
    for t in traces:
        ts = getattr(t, "timestamp", None)
        cost = getattr(t, "total_cost", 0) or 0
        if not ts:
            continue
        if tz_off is not None:
            local_ts = ts + timedelta(minutes=tz_off)
            date_str = local_ts.strftime("%Y-%m-%d")
        else:
            date_str = ts.strftime("%Y-%m-%d")
        daily_costs.setdefault(date_str, []).append(cost)

    # Compute P95 per day
    series = []
    for d in sorted(daily_costs):
        costs = sorted(daily_costs[d])
        if costs:
            p95_idx = min(int(len(costs) * 0.95), len(costs) - 1)
            series.append(TimeseriesPoint(date=d, value=round(costs[p95_idx], 6)))

    return CostTrendResponse(range=range, series=series)
