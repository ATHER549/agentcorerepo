"""Approval API router backed by database tables.

This exposes approval requests for approvers (department admins) and lets them
approve/reject pending PROD publish requests.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.agent_deployment_prod.model import (
    AgentDeploymentProd,
    DeploymentPRODStatusEnum,
    ProdDeploymentLifecycleEnum,
)
from agentcore.services.database.models.agent_registry.model import RegistryDeploymentEnvEnum
from agentcore.services.database.models.approval_request.model import (
    ApprovalDecisionEnum,
    ApprovalRequest,
)
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.folder.model import Folder
from agentcore.services.database.models.mcp_registry.model import McpRegistry, McpRegistryRead, McpRegistryUpdate
from agentcore.services.database.models.mcp_approval_request.model import McpApprovalRequest
from agentcore.services.database.models.model_approval_request.model import (
    ModelApprovalRequest,
    ModelApprovalRequestType,
)
from agentcore.services.database.models.model_audit_log.model import ModelAuditLog
from agentcore.services.database.models.model_registry.model import (
    ModelApprovalStatus,
    ModelEnvironment,
    ModelRegistry,
    ModelVisibilityScope,
)
from agentcore.services.database.models.user.model import User
from agentcore.services.database.registry_service import sync_agent_registry


class SubmittedBy(BaseModel):
    name: str
    avatar: str | None = None


class ApprovalAgent(BaseModel):
    id: str
    entityType: str = "agent"  # agent | mcp | model
    title: str
    status: str  # pending, approved, rejected
    description: str
    submittedBy: SubmittedBy
    project: str
    submitted: str
    version: str
    recentChanges: str
    adminComments: str | None = None
    adminAttachments: list[dict] | None = None


class ApprovalPreviewResponse(BaseModel):
    id: str
    title: str
    version: str
    snapshot: dict


class ApprovalResponse(BaseModel):
    success: bool
    message: str
    agentId: str
    newStatus: str
    timestamp: str
    approvedBy: str | None = None


router = APIRouter(prefix="/approvals", tags=["approvals"])


def _normalize_mcp_mode(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in {"sse", "stdio"}:
        raise HTTPException(status_code=400, detail=f"Unsupported mode '{value}'")
    return normalized


def _normalize_mcp_deployment_env(value: str) -> str:
    normalized = str(value).strip().upper()
    if normalized == "TEST":
        normalized = "DEV"
    if normalized not in {"DEV", "UAT", "PROD"}:
        raise HTTPException(status_code=400, detail=f"Unsupported deployment_env '{value}'")
    return normalized


def _to_status_label(decision: ApprovalDecisionEnum | None) -> str:
    if decision is None:
        return "pending"
    if decision == ApprovalDecisionEnum.APPROVED:
        return "approved"
    return "rejected"


def _to_status_label_any(value: ApprovalDecisionEnum | str | None) -> str:
    if value is None:
        return "pending"
    normalized = str(value).strip().upper()
    if normalized == ApprovalDecisionEnum.APPROVED.value:
        return "approved"
    if normalized == ApprovalDecisionEnum.REJECTED.value:
        return "rejected"
    return "pending"


def _humanize_age(ts: datetime) -> str:
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    total_sec = max(int(delta.total_seconds()), 0)
    if total_sec < 60:
        return f"{total_sec}s ago"
    if total_sec < 3600:
        return f"{total_sec // 60}m ago"
    if total_sec < 86400:
        return f"{total_sec // 3600}h ago"
    return f"{total_sec // 86400}d ago"


def _is_global_approver(user: CurrentActiveUser) -> bool:
    return str(getattr(user, "role", "")).lower() in {"root", "super_admin"}


async def _get_approval_for_action(
    *,
    session: DbSession,
    approval_or_agent_id: str,
    current_user: CurrentActiveUser,
) -> ApprovalRequest:
    req: ApprovalRequest | None = None
    target_uuid: UUID | None = None
    try:
        target_uuid = UUID(approval_or_agent_id)
    except Exception:
        target_uuid = None

    if target_uuid:
        req = (await session.exec(select(ApprovalRequest).where(ApprovalRequest.id == target_uuid))).first()

    if not req and target_uuid:
        stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.agent_id == target_uuid)
            .where(ApprovalRequest.decision == None)  # noqa: E711
            .order_by(ApprovalRequest.requested_at.desc())
        )
        if not _is_global_approver(current_user):
            stmt = stmt.where(ApprovalRequest.request_to == current_user.id)
        req = (await session.exec(stmt)).first()

    if not req:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if not _is_global_approver(current_user) and req.request_to != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to act on this approval")

    return req


async def _get_approval_for_view(
    *,
    session: DbSession,
    approval_or_agent_id: str,
    current_user: CurrentActiveUser,
) -> ApprovalRequest:
    req: ApprovalRequest | None = None
    target_uuid: UUID | None = None
    try:
        target_uuid = UUID(approval_or_agent_id)
    except Exception:
        target_uuid = None

    if not target_uuid:
        raise HTTPException(status_code=404, detail="Approval request not found")

    # Direct match by approval request id.
    req = (await session.exec(select(ApprovalRequest).where(ApprovalRequest.id == target_uuid))).first()
    if req:
        if _is_global_approver(current_user) or req.request_to == current_user.id or req.requested_by == current_user.id:
            return req
        raise HTTPException(status_code=403, detail="Not allowed to view this approval")

    # Fallback by agent id: latest request visible to user.
    stmt = select(ApprovalRequest).where(ApprovalRequest.agent_id == target_uuid).order_by(ApprovalRequest.requested_at.desc())
    if not _is_global_approver(current_user):
        stmt = stmt.where(
            (ApprovalRequest.request_to == current_user.id) | (ApprovalRequest.requested_by == current_user.id)
        )
    req = (await session.exec(stmt)).first()
    if not req:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return req


async def _get_mcp_approval_for_action(
    *,
    session: DbSession,
    approval_or_mcp_id: str,
    current_user: CurrentActiveUser,
) -> McpApprovalRequest:
    target_uuid: UUID | None = None
    try:
        target_uuid = UUID(approval_or_mcp_id)
    except Exception:
        target_uuid = None
    if not target_uuid:
        raise HTTPException(status_code=404, detail="MCP approval request not found")

    req = await session.get(McpApprovalRequest, target_uuid)
    if not req:
        stmt = (
            select(McpApprovalRequest)
            .where(McpApprovalRequest.mcp_id == target_uuid, McpApprovalRequest.decision == None)  # noqa: E711
            .order_by(McpApprovalRequest.requested_at.desc())
        )
        if not _is_global_approver(current_user):
            stmt = stmt.where(McpApprovalRequest.request_to == current_user.id)
        req = (await session.exec(stmt)).first()
    if not req:
        raise HTTPException(status_code=404, detail="MCP approval request not found")
    if not _is_global_approver(current_user) and req.request_to != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to act on this approval")
    return req


async def _get_mcp_approval_for_view(
    *,
    session: DbSession,
    approval_or_mcp_id: str,
    current_user: CurrentActiveUser,
) -> McpApprovalRequest:
    target_uuid: UUID | None = None
    try:
        target_uuid = UUID(approval_or_mcp_id)
    except Exception:
        target_uuid = None
    if not target_uuid:
        raise HTTPException(status_code=404, detail="MCP approval request not found")
    req = await session.get(McpApprovalRequest, target_uuid)
    if not req:
        stmt = select(McpApprovalRequest).where(McpApprovalRequest.mcp_id == target_uuid).order_by(
            McpApprovalRequest.requested_at.desc()
        )
        if not _is_global_approver(current_user):
            stmt = stmt.where(
                (McpApprovalRequest.request_to == current_user.id) | (McpApprovalRequest.requested_by == current_user.id)
            )
        req = (await session.exec(stmt)).first()
    if not req:
        raise HTTPException(status_code=404, detail="MCP approval request not found")
    if _is_global_approver(current_user) or req.request_to == current_user.id or req.requested_by == current_user.id:
        return req
    raise HTTPException(status_code=403, detail="Not allowed to view this approval")


async def _get_model_approval_for_action(
    *,
    session: DbSession,
    approval_or_model_id: str,
    current_user: CurrentActiveUser,
) -> ModelApprovalRequest:
    target_uuid: UUID | None = None
    try:
        target_uuid = UUID(approval_or_model_id)
    except Exception:
        target_uuid = None
    if not target_uuid:
        raise HTTPException(status_code=404, detail="Model approval request not found")

    req = await session.get(ModelApprovalRequest, target_uuid)
    if not req:
        stmt = (
            select(ModelApprovalRequest)
            .where(ModelApprovalRequest.model_id == target_uuid, ModelApprovalRequest.decision == None)  # noqa: E711
            .order_by(ModelApprovalRequest.requested_at.desc())
        )
        # Model approvals are strictly routed — only assigned approver can act
        stmt = stmt.where(ModelApprovalRequest.request_to == current_user.id)
        req = (await session.exec(stmt)).first()
    if not req:
        raise HTTPException(status_code=404, detail="Model approval request not found")
    if req.request_to != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to act on this approval")
    if req.requested_by == current_user.id:
        raise HTTPException(status_code=400, detail="No user can approve their own request")
    return req


async def _get_model_approval_for_view(
    *,
    session: DbSession,
    approval_or_model_id: str,
    current_user: CurrentActiveUser,
) -> ModelApprovalRequest:
    target_uuid: UUID | None = None
    try:
        target_uuid = UUID(approval_or_model_id)
    except Exception:
        target_uuid = None
    if not target_uuid:
        raise HTTPException(status_code=404, detail="Model approval request not found")
    req = await session.get(ModelApprovalRequest, target_uuid)
    if not req:
        stmt = select(ModelApprovalRequest).where(ModelApprovalRequest.model_id == target_uuid).order_by(
            ModelApprovalRequest.requested_at.desc()
        )
        # Model approvals: visible to assigned approver or requester only
        stmt = stmt.where(
            (ModelApprovalRequest.request_to == current_user.id)
            | (ModelApprovalRequest.requested_by == current_user.id)
        )
        req = (await session.exec(stmt)).first()
    if not req:
        raise HTTPException(status_code=404, detail="Model approval request not found")
    if req.request_to == current_user.id or req.requested_by == current_user.id:
        return req
    raise HTTPException(status_code=403, detail="Not allowed to view this approval")


def _next_model_environment(env: str) -> str | None:
    normalized = str(env or "").strip().lower()
    if normalized == ModelEnvironment.TEST.value:
        return ModelEnvironment.UAT.value
    if normalized == ModelEnvironment.UAT.value:
        return ModelEnvironment.PROD.value
    return None


async def _resolve_super_admin_user_id(*, session: DbSession, exclude_user_id: UUID | None = None) -> UUID:
    stmt = select(User).where(User.role == "super_admin").order_by(User.create_at.asc())
    rows = (await session.exec(stmt)).all()
    for row in rows:
        if exclude_user_id and row.id == exclude_user_id:
            continue
        return row.id
    raise HTTPException(status_code=400, detail="No Super Admin approver available")


async def _append_model_audit(
    *,
    session: DbSession,
    model_id: UUID,
    actor_id: UUID | None,
    action: str,
    from_environment: str | None = None,
    to_environment: str | None = None,
    from_visibility: str | None = None,
    to_visibility: str | None = None,
    message: str | None = None,
    details: dict | None = None,
    org_id: UUID | None = None,
    dept_id: UUID | None = None,
) -> None:
    session.add(
        ModelAuditLog(
            model_id=model_id,
            actor_id=actor_id,
            action=action,
            from_environment=from_environment,
            to_environment=to_environment,
            from_visibility=from_visibility,
            to_visibility=to_visibility,
            message=message,
            details=details,
            org_id=org_id,
            dept_id=dept_id,
        )
    )


async def _collect_attachment_metadata(
    *,
    files: list[UploadFile] | None,
    now: datetime,
) -> list[dict]:
    uploaded_files: list[dict] = []
    for file in files or []:
        contents = await file.read()
        uploaded_files.append(
            {
                "filename": file.filename,
                "size": len(contents),
                "uploadedAt": now.isoformat(),
            }
        )
    return uploaded_files


@router.get("", response_model=list[ApprovalAgent])
async def get_approvals(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> list[ApprovalAgent]:
    """Fetch approvals for the current approver."""
    try:
        stmt = select(ApprovalRequest).order_by(ApprovalRequest.requested_at.desc())
        if not _is_global_approver(current_user):
            stmt = stmt.where(ApprovalRequest.request_to == current_user.id)
        rows = (await session.exec(stmt)).all()

        payload: list[ApprovalAgent] = []
        for req in rows:
            deployment = await session.get(AgentDeploymentProd, req.deployment_id)
            if not deployment:
                continue

            requester = await session.get(User, req.requested_by)
            agent = await session.get(Agent, req.agent_id)
            project_name = ""
            if agent and agent.project_id:
                folder = await session.get(Folder, agent.project_id)
                if folder:
                    project_name = folder.name

            title = deployment.agent_name or (agent.name if agent else "Untitled Agent")
            description = deployment.agent_description or req.publish_description or ""
            submitter_name = (
                requester.display_name
                if requester and requester.display_name
                else (requester.username if requester else "Unknown")
            )

            payload.append(
                ApprovalAgent(
                    id=str(req.id),
                    entityType="agent",
                    title=title,
                    status=_to_status_label(req.decision),
                    description=description,
                    submittedBy=SubmittedBy(name=submitter_name, avatar=None),
                    project=project_name,
                    submitted=(
                        req.updated_at.replace(tzinfo=timezone.utc).isoformat()
                        if req.updated_at.tzinfo is None
                        else req.updated_at.isoformat()
                    ),
                    version=f"v{deployment.version_number}",
                    recentChanges="",  # intentionally blank for now
                )
            )

        mcp_stmt = select(McpApprovalRequest).order_by(McpApprovalRequest.requested_at.desc())
        if not _is_global_approver(current_user):
            mcp_stmt = mcp_stmt.where(McpApprovalRequest.request_to == current_user.id)
        mcp_rows = (await session.exec(mcp_stmt)).all()
        for req in mcp_rows:
            row = await session.get(McpRegistry, req.mcp_id)
            if not row:
                continue
            requester = await session.get(User, req.requested_by)
            dept_name = ""
            if req.dept_id:
                dept = await session.get(Department, req.dept_id)
                if dept:
                    dept_name = getattr(dept, "name", "") or ""
            submitter_name = (
                requester.display_name
                if requester and requester.display_name
                else (requester.username if requester else "Unknown")
            )
            submitted_at = req.requested_at
            deployment_env = (req.deployment_env or "DEV").upper()
            payload.append(
                ApprovalAgent(
                    id=str(req.id),
                    entityType="mcp",
                    title=row.server_name,
                    status=_to_status_label_any(req.decision),
                    description=row.description or "",
                    submittedBy=SubmittedBy(name=submitter_name, avatar=None),
                    project=dept_name,
                    submitted=(
                        submitted_at.replace(tzinfo=timezone.utc).isoformat()
                        if submitted_at.tzinfo is None
                        else submitted_at.isoformat()
                    ),
                    version=f"{deployment_env} / {(row.mode or 'mcp').upper()}",
                    recentChanges=f"New MCP server {deployment_env} request",
                )
            )
        model_stmt = select(ModelApprovalRequest).order_by(ModelApprovalRequest.requested_at.desc())
        # Always filter by request_to — each approver only sees their own model requests
        model_stmt = model_stmt.where(ModelApprovalRequest.request_to == current_user.id)
        model_rows = (await session.exec(model_stmt)).all()
        for req in model_rows:
            row = await session.get(ModelRegistry, req.model_id)
            if not row:
                continue
            requester = await session.get(User, req.requested_by)
            dept_name = ""
            if req.dept_id:
                dept = await session.get(Department, req.dept_id)
                if dept:
                    dept_name = getattr(dept, "name", "") or ""
            submitter_name = (
                requester.display_name
                if requester and requester.display_name
                else (requester.username if requester else "Unknown")
            )
            submitted_at = req.requested_at
            # Extract project name from provider_config.request_meta
            provider_cfg = row.provider_config if isinstance(row.provider_config, dict) else {}
            request_meta = provider_cfg.get("request_meta", {})
            model_project_name = request_meta.get("project_name", "") or dept_name
            payload.append(
                ApprovalAgent(
                    id=str(req.id),
                    entityType="model",
                    title=row.display_name,
                    status=_to_status_label_any(req.decision),
                    description=row.description or "",
                    submittedBy=SubmittedBy(name=submitter_name, avatar=None),
                    project=model_project_name,
                    submitted=(
                        submitted_at.replace(tzinfo=timezone.utc).isoformat()
                        if submitted_at.tzinfo is None
                        else submitted_at.isoformat()
                    ),
                    version=f"{row.model_name} ({str(row.environment).upper()})",
                    recentChanges=row.description or "",
                )
            )
        payload.sort(key=lambda item: item.submitted, reverse=True)
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching approvals: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch approvals",
        ) from e


@router.post("/{agent_id}/approve", response_model=ApprovalResponse)
async def approve_agent(
    agent_id: str,
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    comments: str = Form(default=""),
    attachments: list[UploadFile] | None = File(default=None),
) -> ApprovalResponse:
    """Approve a pending deployment request."""
    now = datetime.now(timezone.utc)
    req: ApprovalRequest | None = None
    mcp_req: McpApprovalRequest | None = None
    model_req: ModelApprovalRequest | None = None
    try:
        req = await _get_approval_for_action(
            session=session,
            approval_or_agent_id=agent_id,
            current_user=current_user,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        try:
            mcp_req = await _get_mcp_approval_for_action(
                session=session,
                approval_or_mcp_id=agent_id,
                current_user=current_user,
            )
        except HTTPException as mcp_exc:
            if mcp_exc.status_code != 404:
                raise
            model_req = await _get_model_approval_for_action(
                session=session,
                approval_or_model_id=agent_id,
                current_user=current_user,
            )

    if mcp_req is not None:
        if mcp_req.decision is not None:
            raise HTTPException(status_code=400, detail="MCP approval request already finalized")
        mcp_row = await session.get(McpRegistry, mcp_req.mcp_id)
        if not mcp_row:
            raise HTTPException(status_code=404, detail="Linked MCP server not found")
        uploaded_files = await _collect_attachment_metadata(files=attachments, now=now)
        if not comments.strip() and not uploaded_files:
            raise HTTPException(
                status_code=400,
                detail="Either comments or attachments are required for approval",
            )
        mcp_req.decision = ApprovalDecisionEnum.APPROVED
        mcp_req.justification = comments.strip() if comments else None
        existing = mcp_req.file_path if isinstance(mcp_req.file_path, dict) else {}
        existing_files = existing.get("files", [])
        if uploaded_files:
            existing["files"] = [*existing_files, *uploaded_files]
            mcp_req.file_path = existing
        mcp_req.reviewed_at = now
        mcp_req.updated_at = now

        mcp_row.approval_status = "approved"
        mcp_row.review_comments = mcp_req.justification
        mcp_row.review_attachments = mcp_req.file_path
        mcp_row.reviewed_at = now
        mcp_row.reviewed_by = current_user.id
        mcp_row.is_active = True
        mcp_row.status = "connected"
        mcp_row.updated_at = now
        session.add(mcp_req)
        session.add(mcp_row)
        await session.commit()
        approver_name = getattr(current_user, "username", None)
        return ApprovalResponse(
            success=True,
            message="MCP request approved successfully",
            agentId=str(mcp_req.id),
            newStatus="approved",
            timestamp=now.isoformat(),
            approvedBy=approver_name,
        )

    if model_req is not None:
        if model_req.decision is not None:
            raise HTTPException(status_code=400, detail="Model approval request already finalized")
        model_row = await session.get(ModelRegistry, model_req.model_id)
        if not model_row:
            raise HTTPException(status_code=404, detail="Linked model not found")
        uploaded_files = await _collect_attachment_metadata(files=attachments, now=now)
        if not comments.strip() and not uploaded_files:
            raise HTTPException(
                status_code=400,
                detail="Either comments or attachments are required for approval",
            )
        model_req.decision = ApprovalDecisionEnum.APPROVED
        model_req.justification = comments.strip() if comments else None
        existing = model_req.file_path if isinstance(model_req.file_path, dict) else {}
        existing_files = existing.get("files", [])
        if uploaded_files:
            existing["files"] = [*existing_files, *uploaded_files]
            model_req.file_path = existing
        model_req.reviewed_at = now
        model_req.updated_at = now

        current_env = str(model_row.environment or ModelEnvironment.TEST.value).lower()
        current_visibility = str(model_row.visibility_scope or ModelVisibilityScope.PRIVATE.value).lower()
        model_row.review_comments = model_req.justification
        model_row.review_attachments = model_req.file_path
        model_row.reviewed_at = now
        model_row.reviewed_by = current_user.id
        model_row.updated_at = now

        if model_req.request_type == ModelApprovalRequestType.PROMOTE:
            expected_next = _next_model_environment(current_env)
            if not expected_next or str(model_req.target_environment).lower() != expected_next:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid promotion path. Backend enforces DEV->UAT->PROD only.",
                )
            if current_env == ModelEnvironment.TEST.value and str(model_req.target_environment).lower() == ModelEnvironment.PROD.value:
                raise HTTPException(status_code=400, detail="Direct DEV->PROD promotion is blocked")
            model_row.environment = str(model_req.target_environment).lower()
            model_row.approval_status = ModelApprovalStatus.APPROVED.value
            model_row.is_active = True
            model_row.request_to = None
            model_row.requested_at = None
            model_row.requested_by = model_req.requested_by
            await _append_model_audit(
                session=session,
                model_id=model_row.id,
                actor_id=current_user.id,
                action="model.promotion.approved",
                from_environment=current_env,
                to_environment=model_row.environment,
                message="Model promotion approved",
                org_id=model_row.org_id,
                dept_id=model_row.dept_id,
            )

            if (
                str(model_req.final_target_environment or "").lower() == ModelEnvironment.PROD.value
                and str(model_req.target_environment).lower() == ModelEnvironment.UAT.value
            ):
                super_admin_id = await _resolve_super_admin_user_id(
                    session=session,
                    exclude_user_id=model_req.requested_by,
                )
                follow_up = ModelApprovalRequest(
                    model_id=model_row.id,
                    org_id=model_row.org_id,
                    dept_id=model_row.dept_id,
                    request_type=ModelApprovalRequestType.PROMOTE,
                    source_environment=ModelEnvironment.UAT.value,
                    target_environment=ModelEnvironment.PROD.value,
                    final_target_environment=None,
                    visibility_requested=model_row.visibility_scope,
                    requested_by=model_req.requested_by,
                    request_to=super_admin_id,
                    requested_at=now,
                )
                session.add(follow_up)
                model_row.approval_status = ModelApprovalStatus.PENDING.value
                model_row.request_to = super_admin_id
                model_row.requested_at = now
                model_row.is_active = False
                await _append_model_audit(
                    session=session,
                    model_id=model_row.id,
                    actor_id=current_user.id,
                    action="model.promotion.requested",
                    from_environment=ModelEnvironment.UAT.value,
                    to_environment=ModelEnvironment.PROD.value,
                    message="Auto-created UAT->PROD promotion request",
                    details={"auto_chained": True},
                    org_id=model_row.org_id,
                    dept_id=model_row.dept_id,
                )
        elif model_req.request_type == ModelApprovalRequestType.VISIBILITY:
            model_row.visibility_scope = str(model_req.visibility_requested).lower()
            model_row.approval_status = ModelApprovalStatus.APPROVED.value
            model_row.is_active = True
            model_row.request_to = None
            model_row.requested_at = None
            await _append_model_audit(
                session=session,
                model_id=model_row.id,
                actor_id=current_user.id,
                action="model.visibility.approved",
                from_visibility=current_visibility,
                to_visibility=model_row.visibility_scope,
                message="Model visibility change approved",
                org_id=model_row.org_id,
                dept_id=model_row.dept_id,
            )
        else:
            # CREATE type: apply both visibility and environment changes
            model_row.visibility_scope = str(model_req.visibility_requested or current_visibility).lower()
            target_env = str(model_req.target_environment or current_env).lower()
            model_row.environment = target_env or current_env

            model_row.approval_status = ModelApprovalStatus.APPROVED.value
            model_row.is_active = True
            model_row.request_to = None
            model_row.requested_at = None

            await _append_model_audit(
                session=session,
                model_id=model_row.id,
                actor_id=current_user.id,
                action="model.create.approved",
                from_environment=current_env,
                to_environment=model_row.environment,
                from_visibility=current_visibility,
                to_visibility=model_row.visibility_scope,
                message="Model onboarding request approved",
                org_id=model_row.org_id,
                dept_id=model_row.dept_id,
            )

            # CREATE requests are completed in a single approval step.
        session.add(model_req)
        session.add(model_row)
        await session.commit()
        approver_name = getattr(current_user, "username", None)
        return ApprovalResponse(
            success=True,
            message="Model request approved successfully",
            agentId=str(model_req.id),
            newStatus="approved",
            timestamp=now.isoformat(),
            approvedBy=approver_name,
        )

    assert req is not None
    if req.decision is not None:
        raise HTTPException(status_code=400, detail="Approval request already finalized")

    deployment = await session.get(AgentDeploymentProd, req.deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Linked deployment not found")

    uploaded_files = await _collect_attachment_metadata(files=attachments, now=now)
    if not comments.strip() and not uploaded_files:
        raise HTTPException(
            status_code=400,
            detail="Either comments or attachments are required for approval",
        )

    req.decision = ApprovalDecisionEnum.APPROVED
    req.justification = comments.strip() if comments else None
    existing = req.file_path if isinstance(req.file_path, dict) else {}
    existing_files = existing.get("files", [])
    if uploaded_files:
        existing["files"] = [*existing_files, *uploaded_files]
        req.file_path = existing
    req.reviewed_at = now
    req.updated_at = now
    session.add(req)

    deployment.status = DeploymentPRODStatusEnum.PUBLISHED
    deployment.lifecycle_step = ProdDeploymentLifecycleEnum.PUBLISHED
    deployment.is_active = True
    deployment.approval_id = req.id
    deployment.updated_at = now
    session.add(deployment)

    # Shadow deployment: keep previous versions active so
    # multiple versions can run side-by-side.

    await session.commit()

    try:
        await sync_agent_registry(
            session,
            agent_id=deployment.agent_id,
            org_id=deployment.org_id,
            acted_by=current_user.id,
            deployment_env=RegistryDeploymentEnvEnum.PROD,
        )
        await session.commit()
    except Exception as reg_err:
        logger.warning(f"Registry sync failed after approval {req.id}: {reg_err}")

    # Sync FileTrigger nodes → auto-create trigger_config entries
    if deployment.agent_snapshot:
        try:
            from agentcore.services.deps import get_trigger_service
            trigger_svc = get_trigger_service()
            await trigger_svc.sync_folder_monitors_for_agent(
                session=session,
                agent_id=deployment.agent_id,
                environment="prod",
                version=f"v{deployment.version_number}",
                deployment_id=deployment.id,
                flow_data=deployment.agent_snapshot,
                created_by=req.requested_by,
            )
        except Exception as fm_err:
            logger.warning(f"FileTrigger sync failed after approval {req.id}: {fm_err}")

    approver_name = getattr(current_user, "username", None)
    return ApprovalResponse(
        success=True,
        message="Agent approved successfully",
        agentId=str(req.agent_id),
        newStatus="approved",
        timestamp=now.isoformat(),
        approvedBy=approver_name,
    )


@router.post("/{agent_id}/reject", response_model=ApprovalResponse)
async def reject_agent(
    agent_id: str,
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    comments: str = Form(default=""),
    reason: str | None = Form(default=None),
    attachments: list[UploadFile] | None = File(default=None),
) -> ApprovalResponse:
    """Reject a pending deployment request."""
    now = datetime.now(timezone.utc)
    req: ApprovalRequest | None = None
    mcp_req: McpApprovalRequest | None = None
    model_req: ModelApprovalRequest | None = None
    try:
        req = await _get_approval_for_action(
            session=session,
            approval_or_agent_id=agent_id,
            current_user=current_user,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        try:
            mcp_req = await _get_mcp_approval_for_action(
                session=session,
                approval_or_mcp_id=agent_id,
                current_user=current_user,
            )
        except HTTPException as mcp_exc:
            if mcp_exc.status_code != 404:
                raise
            model_req = await _get_model_approval_for_action(
                session=session,
                approval_or_model_id=agent_id,
                current_user=current_user,
            )

    if mcp_req is not None:
        if mcp_req.decision is not None:
            raise HTTPException(status_code=400, detail="MCP approval request already finalized")
        mcp_row = await session.get(McpRegistry, mcp_req.mcp_id)
        if not mcp_row:
            raise HTTPException(status_code=404, detail="Linked MCP server not found")
        uploaded_files = await _collect_attachment_metadata(files=attachments, now=now)
        if not comments.strip() and not uploaded_files:
            raise HTTPException(
                status_code=400,
                detail="Either comments or attachments are required for rejection",
            )
        rejection_reason = reason or "Not approved"
        justification = comments.strip()
        mcp_req.decision = ApprovalDecisionEnum.REJECTED
        mcp_req.justification = f"{rejection_reason}: {justification}" if justification else rejection_reason
        existing = mcp_req.file_path if isinstance(mcp_req.file_path, dict) else {}
        existing_files = existing.get("files", [])
        if uploaded_files:
            existing["files"] = [*existing_files, *uploaded_files]
            mcp_req.file_path = existing
        mcp_req.reviewed_at = now
        mcp_req.updated_at = now

        mcp_row.approval_status = "rejected"
        mcp_row.review_comments = mcp_req.justification
        mcp_row.review_attachments = mcp_req.file_path
        mcp_row.reviewed_at = now
        mcp_row.reviewed_by = current_user.id
        mcp_row.is_active = False
        mcp_row.status = "rejected"
        mcp_row.updated_at = now
        session.add(mcp_req)
        session.add(mcp_row)
        await session.commit()
        approver_name = getattr(current_user, "username", None)
        return ApprovalResponse(
            success=True,
            message="MCP request rejected",
            agentId=str(mcp_req.id),
            newStatus="rejected",
            timestamp=now.isoformat(),
            approvedBy=approver_name,
        )

    if model_req is not None:
        if model_req.decision is not None:
            raise HTTPException(status_code=400, detail="Model approval request already finalized")
        model_row = await session.get(ModelRegistry, model_req.model_id)
        if not model_row:
            raise HTTPException(status_code=404, detail="Linked model not found")
        uploaded_files = await _collect_attachment_metadata(files=attachments, now=now)
        if not comments.strip() and not uploaded_files:
            raise HTTPException(
                status_code=400,
                detail="Either comments or attachments are required for rejection",
            )
        rejection_reason = reason or "Not approved"
        justification = comments.strip()
        model_req.decision = ApprovalDecisionEnum.REJECTED
        model_req.justification = f"{rejection_reason}: {justification}" if justification else rejection_reason
        existing = model_req.file_path if isinstance(model_req.file_path, dict) else {}
        existing_files = existing.get("files", [])
        if uploaded_files:
            existing["files"] = [*existing_files, *uploaded_files]
            model_req.file_path = existing
        model_req.reviewed_at = now
        model_req.updated_at = now

        model_row.approval_status = ModelApprovalStatus.REJECTED.value
        model_row.review_comments = model_req.justification
        model_row.review_attachments = model_req.file_path
        model_row.reviewed_at = now
        model_row.reviewed_by = current_user.id
        model_row.is_active = False
        model_row.updated_at = now
        session.add(model_req)
        session.add(model_row)
        await _append_model_audit(
            session=session,
            model_id=model_row.id,
            actor_id=current_user.id,
            action="model.request.rejected",
            from_environment=model_row.environment,
            to_environment=model_row.environment,
            from_visibility=model_row.visibility_scope,
            to_visibility=model_row.visibility_scope,
            message="Model approval request rejected",
            org_id=model_row.org_id,
            dept_id=model_row.dept_id,
            details={"request_type": str(model_req.request_type)},
        )
        await session.commit()
        approver_name = getattr(current_user, "username", None)
        return ApprovalResponse(
            success=True,
            message="Model request rejected",
            agentId=str(model_req.id),
            newStatus="rejected",
            timestamp=now.isoformat(),
            approvedBy=approver_name,
        )

    assert req is not None
    if req.decision is not None:
        raise HTTPException(status_code=400, detail="Approval request already finalized")

    deployment = await session.get(AgentDeploymentProd, req.deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Linked deployment not found")

    uploaded_files = await _collect_attachment_metadata(files=attachments, now=now)
    if not comments.strip() and not uploaded_files:
        raise HTTPException(
            status_code=400,
            detail="Either comments or attachments are required for rejection",
        )

    rejection_reason = reason or "Not approved"
    justification = comments.strip()
    req.decision = ApprovalDecisionEnum.REJECTED
    req.justification = f"{rejection_reason}: {justification}" if justification else rejection_reason
    existing = req.file_path if isinstance(req.file_path, dict) else {}
    existing_files = existing.get("files", [])
    if uploaded_files:
        existing["files"] = [*existing_files, *uploaded_files]
        req.file_path = existing
    req.reviewed_at = now
    req.updated_at = now
    session.add(req)

    deployment.status = DeploymentPRODStatusEnum.UNPUBLISHED
    deployment.is_active = False
    deployment.updated_at = now
    session.add(deployment)

    await session.commit()

    approver_name = getattr(current_user, "username", None)
    return ApprovalResponse(
        success=True,
        message="Agent rejected",
        agentId=str(req.agent_id),
        newStatus="rejected",
        timestamp=now.isoformat(),
        approvedBy=approver_name,
    )


@router.post("/{agent_id}/attachments")
async def upload_attachments(
    agent_id: str,
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    attachments: list[UploadFile] = File(...),
):
    """Attach metadata of uploaded files to approval request."""
    req: ApprovalRequest | None = None
    mcp_req: McpApprovalRequest | None = None
    model_req: ModelApprovalRequest | None = None
    try:
        req = await _get_approval_for_action(
            session=session,
            approval_or_agent_id=agent_id,
            current_user=current_user,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        try:
            mcp_req = await _get_mcp_approval_for_action(
                session=session,
                approval_or_mcp_id=agent_id,
                current_user=current_user,
            )
        except HTTPException as mcp_exc:
            if mcp_exc.status_code != 404:
                raise
            model_req = await _get_model_approval_for_action(
                session=session,
                approval_or_model_id=agent_id,
                current_user=current_user,
            )
    uploaded_files: list[dict] = []
    now = datetime.now(timezone.utc)
    for file in attachments:
        contents = await file.read()
        uploaded_files.append(
            {
                "filename": file.filename,
                "size": len(contents),
                "uploadedAt": now.isoformat(),
            }
        )

    if mcp_req is not None:
        mcp_row = await session.get(McpRegistry, mcp_req.mcp_id)
        if not mcp_row:
            raise HTTPException(status_code=404, detail="Linked MCP server not found")
        existing = mcp_req.file_path if isinstance(mcp_req.file_path, dict) else {}
        existing_files = existing.get("files", [])
        existing["files"] = [*existing_files, *uploaded_files]
        mcp_req.file_path = existing
        mcp_req.updated_at = now
        mcp_row.review_attachments = existing
        mcp_row.updated_at = now
        session.add(mcp_req)
        session.add(mcp_row)
    elif model_req is not None:
        model_row = await session.get(ModelRegistry, model_req.model_id)
        if not model_row:
            raise HTTPException(status_code=404, detail="Linked model not found")
        existing = model_req.file_path if isinstance(model_req.file_path, dict) else {}
        existing_files = existing.get("files", [])
        existing["files"] = [*existing_files, *uploaded_files]
        model_req.file_path = existing
        model_req.updated_at = now
        model_row.review_attachments = existing
        model_row.updated_at = now
        session.add(model_req)
        session.add(model_row)
    else:
        assert req is not None
        existing = req.file_path if isinstance(req.file_path, dict) else {}
        existing_files = existing.get("files", [])
        existing["files"] = [*existing_files, *uploaded_files]
        req.file_path = existing
        req.updated_at = now
        session.add(req)
    await session.commit()

    return {
        "success": True,
        "message": "Attachments uploaded successfully",
        "agentId": str(
            mcp_req.id if mcp_req is not None else (model_req.id if model_req is not None else req.agent_id)
        ),
        "uploadedFiles": uploaded_files,
    }


@router.get("/{agent_id}", response_model=ApprovalAgent)
async def get_agent_details(
    agent_id: str,
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> ApprovalAgent:
    req: ApprovalRequest | None = None
    mcp_req: McpApprovalRequest | None = None
    model_req: ModelApprovalRequest | None = None
    try:
        req = await _get_approval_for_view(
            session=session,
            approval_or_agent_id=agent_id,
            current_user=current_user,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        try:
            mcp_req = await _get_mcp_approval_for_view(
                session=session,
                approval_or_mcp_id=agent_id,
                current_user=current_user,
            )
        except HTTPException as mcp_exc:
            if mcp_exc.status_code != 404:
                raise
            model_req = await _get_model_approval_for_view(
                session=session,
                approval_or_model_id=agent_id,
                current_user=current_user,
            )
    if mcp_req is not None:
        row = await session.get(McpRegistry, mcp_req.mcp_id)
        if not row:
            raise HTTPException(status_code=404, detail="Linked MCP server not found")
        requester = await session.get(User, mcp_req.requested_by)
        submitted_at = mcp_req.requested_at
        return ApprovalAgent(
            id=str(mcp_req.id),
            entityType="mcp",
            title=row.server_name,
            status=_to_status_label_any(mcp_req.decision),
            description=row.description or "",
            submittedBy=SubmittedBy(
                name=(
                    requester.display_name
                    if requester and requester.display_name
                    else (requester.username if requester else "Unknown")
                ),
                avatar=None,
            ),
            project="",
            submitted=(
                submitted_at.replace(tzinfo=timezone.utc).isoformat()
                if submitted_at.tzinfo is None
                else submitted_at.isoformat()
            ),
            version=f"{(mcp_req.deployment_env or 'DEV').upper()} / {(row.mode or 'mcp').upper()}",
            recentChanges="New MCP server request",
            adminComments=mcp_req.justification,
            adminAttachments=(mcp_req.file_path.get("files", []) if isinstance(mcp_req.file_path, dict) else []),
        )
    if model_req is not None:
        row = await session.get(ModelRegistry, model_req.model_id)
        if not row:
            raise HTTPException(status_code=404, detail="Linked model not found")
        requester = await session.get(User, model_req.requested_by)
        submitted_at = model_req.requested_at
        provider_cfg = row.provider_config if isinstance(row.provider_config, dict) else {}
        request_meta = provider_cfg.get("request_meta", {})
        model_project_name = request_meta.get("project_name", "")
        return ApprovalAgent(
            id=str(model_req.id),
            entityType="model",
            title=row.display_name,
            status=_to_status_label_any(model_req.decision),
            description=row.description or "",
            submittedBy=SubmittedBy(
                name=(
                    requester.display_name
                    if requester and requester.display_name
                    else (requester.username if requester else "Unknown")
                ),
                avatar=None,
            ),
            project=model_project_name,
            submitted=(
                submitted_at.replace(tzinfo=timezone.utc).isoformat()
                if submitted_at.tzinfo is None
                else submitted_at.isoformat()
            ),
            version=f"{row.model_name} ({str(row.environment).upper()})",
            recentChanges=row.description or "",
            adminComments=model_req.justification,
            adminAttachments=(model_req.file_path.get("files", []) if isinstance(model_req.file_path, dict) else []),
        )
    assert req is not None
    deployment = await session.get(AgentDeploymentProd, req.deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Linked deployment not found")
    requester = await session.get(User, req.requested_by)
    agent = await session.get(Agent, req.agent_id)
    project_name = ""
    if agent and agent.project_id:
        folder = await session.get(Folder, agent.project_id)
        if folder:
            project_name = folder.name

    return ApprovalAgent(
        id=str(req.id),
        entityType="agent",
        title=deployment.agent_name or (agent.name if agent else "Untitled Agent"),
        status=_to_status_label(req.decision),
        description=deployment.agent_description or req.publish_description or "",
        submittedBy=SubmittedBy(
            name=(requester.display_name if requester and requester.display_name else (requester.username if requester else "Unknown")),
            avatar=None,
        ),
        project=project_name,
        submitted=(
            req.updated_at.replace(tzinfo=timezone.utc).isoformat()
            if req.updated_at.tzinfo is None
            else req.updated_at.isoformat()
        ),
        version=f"v{deployment.version_number}",
        recentChanges="",  # intentionally blank for now
        adminComments=req.justification,
        adminAttachments=(req.file_path.get("files", []) if isinstance(req.file_path, dict) else []),
    )


@router.get("/{agent_id}/mcp-config", response_model=McpRegistryRead)
async def get_mcp_config_for_approval(
    agent_id: str,
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> McpRegistryRead:
    """Return editable MCP configuration linked to an approval request."""
    mcp_req = await _get_mcp_approval_for_view(
        session=session,
        approval_or_mcp_id=agent_id,
        current_user=current_user,
    )
    row = await session.get(McpRegistry, mcp_req.mcp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Linked MCP server not found")
    return McpRegistryRead.from_orm_model(row)


@router.put("/{agent_id}/mcp-config", response_model=McpRegistryRead)
async def update_mcp_config_for_approval(
    agent_id: str,
    payload: McpRegistryUpdate,
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> McpRegistryRead:
    """Update MCP config during review; only approver assigned to pending request can edit."""
    mcp_req = await _get_mcp_approval_for_action(
        session=session,
        approval_or_mcp_id=agent_id,
        current_user=current_user,
    )
    if mcp_req.decision is not None:
        raise HTTPException(status_code=400, detail="MCP approval request already finalized")

    row = await session.get(McpRegistry, mcp_req.mcp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Linked MCP server not found")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return McpRegistryRead.from_orm_model(row)

    if "server_name" in updates and isinstance(updates["server_name"], str):
        candidate_name = updates["server_name"].strip().lower()
        existing = (
            await session.exec(
                select(McpRegistry.id).where(
                    func.lower(McpRegistry.server_name) == candidate_name,
                    McpRegistry.id != row.id,
                )
            )
        ).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="MCP server name already exists")
        updates["server_name"] = updates["server_name"].strip()

    if "mode" in updates and updates["mode"] is not None:
        updates["mode"] = _normalize_mcp_mode(updates["mode"])
    effective_mode = updates.get("mode", row.mode)

    if "deployment_env" in updates and updates["deployment_env"] is not None:
        updates["deployment_env"] = _normalize_mcp_deployment_env(updates["deployment_env"])

    # Keep transport fields coherent whenever mode changes.
    if effective_mode == "sse":
        updates["command"] = None
        updates["args"] = None
    elif effective_mode == "stdio":
        updates["url"] = None

    allowed_fields = {
        "server_name",
        "description",
        "mode",
        "deployment_env",
        "url",
        "command",
        "args",
        "visibility",
        "public_scope",
        "public_dept_ids",
        "org_id",
        "dept_id",
    }
    for field_name, value in updates.items():
        if field_name in allowed_fields:
            setattr(row, field_name, value)

    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return McpRegistryRead.from_orm_model(row)


@router.get("/{agent_id}/preview", response_model=ApprovalPreviewResponse)
async def get_agent_preview(
    agent_id: str,
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
) -> ApprovalPreviewResponse:
    req: ApprovalRequest | None = None
    mcp_req: McpApprovalRequest | None = None
    model_req: ModelApprovalRequest | None = None
    try:
        req = await _get_approval_for_view(
            session=session,
            approval_or_agent_id=agent_id,
            current_user=current_user,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        try:
            mcp_req = await _get_mcp_approval_for_view(
                session=session,
                approval_or_mcp_id=agent_id,
                current_user=current_user,
            )
        except HTTPException as mcp_exc:
            if mcp_exc.status_code != 404:
                raise
            model_req = await _get_model_approval_for_view(
                session=session,
                approval_or_model_id=agent_id,
                current_user=current_user,
            )
    if mcp_req is not None:
        row = await session.get(McpRegistry, mcp_req.mcp_id)
        if not row:
            raise HTTPException(status_code=404, detail="Linked MCP server not found")
        return ApprovalPreviewResponse(
            id=str(mcp_req.id),
            title=row.server_name,
            version=f"{(mcp_req.deployment_env or 'DEV').upper()} / {(row.mode or 'mcp').upper()}",
            snapshot={
                "server_name": row.server_name,
                "description": row.description,
                "mode": row.mode,
                "deployment_env": mcp_req.deployment_env,
                "url": row.url,
                "command": row.command,
                "args": row.args,
                "visibility": row.visibility,
                "public_scope": row.public_scope,
                "org_id": str(row.org_id) if row.org_id else None,
                "dept_id": str(row.dept_id) if row.dept_id else None,
                "approval_status": row.approval_status,
            },
        )
    if model_req is not None:
        row = await session.get(ModelRegistry, model_req.model_id)
        if not row:
            raise HTTPException(status_code=404, detail="Linked model not found")
        return ApprovalPreviewResponse(
            id=str(model_req.id),
            title=row.display_name,
            version=f"{str(row.environment).upper()} / {str(row.model_type).upper()}",
            snapshot={
                "model_id": str(row.id),
                "display_name": row.display_name,
                "description": row.description,
                "provider": row.provider,
                "model_name": row.model_name,
                "model_type": row.model_type,
                "environment": row.environment,
                "requested_type": str(model_req.request_type),
                "source_environment": model_req.source_environment,
                "target_environment": model_req.target_environment,
                "final_target_environment": model_req.final_target_environment,
                "visibility_requested": model_req.visibility_requested,
                "visibility_scope": row.visibility_scope,
                "org_id": str(row.org_id) if row.org_id else None,
                "dept_id": str(row.dept_id) if row.dept_id else None,
                "approval_status": row.approval_status,
                "provider_config": row.provider_config,
                "capabilities": row.capabilities,
                "default_params": row.default_params,
            },
        )
    assert req is not None
    deployment = await session.get(AgentDeploymentProd, req.deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Linked deployment not found")

    if not deployment.agent_snapshot:
        raise HTTPException(
            status_code=404,
            detail="No deployment snapshot found for preview",
        )

    return ApprovalPreviewResponse(
        id=str(req.id),
        title=deployment.agent_name or "Review Details",
        version=f"v{deployment.version_number}",
        snapshot=deployment.agent_snapshot,
    )


@router.post("/{agent_id}/reset-status")
async def reset_agent_status(
    agent_id: str,
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Reset status back to pending (kept for testing/demo utility)."""
    req: ApprovalRequest | None = None
    mcp_req: McpApprovalRequest | None = None
    model_req: ModelApprovalRequest | None = None
    try:
        req = await _get_approval_for_action(
            session=session,
            approval_or_agent_id=agent_id,
            current_user=current_user,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        try:
            mcp_req = await _get_mcp_approval_for_action(
                session=session,
                approval_or_mcp_id=agent_id,
                current_user=current_user,
            )
        except HTTPException as mcp_exc:
            if mcp_exc.status_code != 404:
                raise
            model_req = await _get_model_approval_for_action(
                session=session,
                approval_or_model_id=agent_id,
                current_user=current_user,
            )
    if mcp_req is not None:
        now = datetime.now(timezone.utc)
        mcp_row = await session.get(McpRegistry, mcp_req.mcp_id)
        if not mcp_row:
            raise HTTPException(status_code=404, detail="Linked MCP server not found")
        mcp_req.decision = None
        mcp_req.reviewed_at = None
        mcp_req.updated_at = now
        mcp_row.approval_status = "pending"
        mcp_row.reviewed_at = None
        mcp_row.reviewed_by = None
        mcp_row.is_active = False
        mcp_row.status = "pending_approval"
        mcp_row.updated_at = now
        session.add(mcp_req)
        session.add(mcp_row)
        await session.commit()
        return {
            "success": True,
            "message": "MCP status reset to pending",
            "agentId": str(mcp_req.id),
            "newStatus": "pending",
        }
    if model_req is not None:
        now = datetime.now(timezone.utc)
        model_row = await session.get(ModelRegistry, model_req.model_id)
        if not model_row:
            raise HTTPException(status_code=404, detail="Linked model not found")
        model_req.decision = None
        model_req.reviewed_at = None
        model_req.updated_at = now
        model_row.approval_status = ModelApprovalStatus.PENDING.value
        model_row.reviewed_at = None
        model_row.reviewed_by = None
        model_row.is_active = False
        model_row.updated_at = now
        session.add(model_req)
        session.add(model_row)
        await _append_model_audit(
            session=session,
            model_id=model_row.id,
            actor_id=current_user.id,
            action="model.request.reset_pending",
            message="Model approval reset to pending",
            org_id=model_row.org_id,
            dept_id=model_row.dept_id,
            details={"request_type": str(model_req.request_type)},
        )
        await session.commit()
        return {
            "success": True,
            "message": "Model status reset to pending",
            "agentId": str(model_req.id),
            "newStatus": "pending",
        }
    assert req is not None
    deployment = await session.get(AgentDeploymentProd, req.deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Linked deployment not found")

    now = datetime.now(timezone.utc)
    req.decision = None
    req.reviewed_at = None
    req.updated_at = now
    session.add(req)

    deployment.status = DeploymentPRODStatusEnum.PENDING_APPROVAL
    deployment.is_active = False
    deployment.updated_at = now
    session.add(deployment)

    await session.commit()
    return {
        "success": True,
        "message": "Agent status reset to pending",
        "agentId": str(req.agent_id),
        "newStatus": "pending",
    }
