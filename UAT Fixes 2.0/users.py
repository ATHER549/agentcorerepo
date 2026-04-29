from datetime import datetime, timezone
import csv
import io
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, distinct, exists, func, or_, asc, desc, delete, update, inspect
from sqlalchemy.sql import column, table
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.sql.expression import SelectOfScalar

from agentcore.api.schemas import UsersResponse, UserReadWithPermissions
from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.decorators import PermissionChecker
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role, permission_cache
from agentcore.services.auth.invalidation import invalidate_user_auth
from agentcore.services.auth.utils import get_password_hash, verify_password
from agentcore.services.cache.user_cache import UserCacheService
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.agent_api_key.model import AgentApiKey
from agentcore.services.database.models.agent_bundle.model import AgentBundle
from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd, DeploymentPRODStatusEnum
from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT, DeploymentUATStatusEnum
from agentcore.services.database.models.agent_edit_lock.model import AgentEditLock
from agentcore.services.database.models.agent_publish_recipient.model import AgentPublishRecipient
from agentcore.services.database.models.agent_registry.model import AgentRegistry, AgentRegistryRating
from agentcore.services.database.models.approval_request.model import ApprovalRequest
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.file.model import File
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.project.model import Project
from agentcore.services.database.models.role.model import Role
from agentcore.services.database.models.user.crud import get_user_by_id, update_user
from agentcore.services.database.models.user.model import User, UserCreate, UserRead, UserUpdate
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.deps import get_settings_service
from agentcore.services.notifications import send_user_notification_email
from agentcore.services.observability import (
    LangfuseProvisioningError,
    get_langfuse_provisioning_service,
)

router = APIRouter(tags=["Users"], prefix="/users")

ACTIVE_ORG_STATUSES = {"accepted", "active"}
ACTIVE_DEPT_STATUS = "active"
NON_ASSIGNABLE_ROLES = {"consumer"}
ORG_SCOPED_NON_DEPARTMENT_ROLES = {"leader_executive"}


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def _table_exists(session: DbSession, table_name: str) -> bool:
    connection = await session.connection()
    return await connection.run_sync(
        lambda sync_connection: table_name in inspect(sync_connection).get_table_names()
    )


def _normalize_identity(value: str | None) -> str | None:
    stripped = _strip_or_none(value)
    if not stripped:
        return None
    return stripped.lower() if "@" in stripped else stripped


def _normalize_name_key(value: str | None) -> str | None:
    stripped = _strip_or_none(value)
    if not stripped:
        return None
    return stripped.lower()


async def _find_organization_by_normalized_name(
    session: DbSession,
    organization_name: str | None,
) -> Organization | None:
    normalized_name = _normalize_name_key(organization_name)
    if not normalized_name:
        return None
    return (
        await session.exec(
            select(Organization).where(
                func.lower(func.trim(Organization.name)) == normalized_name,
            )
        )
    ).first()


async def _find_department_by_normalized_name(
    session: DbSession,
    *,
    org_id: UUID,
    department_name: str | None,
) -> Department | None:
    normalized_name = _normalize_name_key(department_name)
    if not normalized_name:
        return None
    return (
        await session.exec(
            select(Department).where(
                Department.org_id == org_id,
                func.lower(func.trim(Department.name)) == normalized_name,
            )
        )
    ).first()


def _ensure_department_name_differs_from_org(
    *,
    department_name: str | None,
    organization_name: str | None,
) -> None:
    department_key = _normalize_name_key(department_name)
    organization_key = _normalize_name_key(organization_name)
    if department_key and organization_key and department_key == organization_key:
        raise HTTPException(
            status_code=400,
            detail="Department name cannot be the same as the organization name.",
        )


def _format_notification_email_status(
    response: Response,
    *,
    sent: bool,
    detail: str | None = None,
) -> None:
    response.headers["X-Agentcore-Notification-Email-Status"] = "sent" if sent else "not_sent"
    if sent:
        return
    response.headers["X-Agentcore-Warning-Title"] = "Email not sent"
    response.headers["X-Agentcore-Warning"] = (
        detail
        or "Notification email could not be sent."
    )


def _notification_recipient_for_user(target_user: User) -> str | None:
    email = _normalize_identity(getattr(target_user, "email", None))
    if email:
        return email
    username = _normalize_identity(getattr(target_user, "username", None))
    if username and "@" in username:
        return username
    return None


def _display_name_for_user(target_user: User) -> str:
    return (
        _strip_or_none(getattr(target_user, "display_name", None))
        or _strip_or_none(getattr(target_user, "username", None))
        or "User"
    )


def _friendly_role_name(role_name: str | None) -> str:
    normalized = normalize_role(role_name or "")
    return normalized.replace("_", " ").title() if normalized else "-"


def _build_add_user_email_details(target_user: User) -> list[str]:
    details = [
        f"Username: {target_user.username}",
        f"Role: {_friendly_role_name(target_user.role)}",
        f"Status: {'Active' if target_user.is_active else 'Inactive'}",
    ]
    if target_user.department_name:
        details.append(f"Department: {target_user.department_name}")
    return details


def _build_update_user_email_details(
    *,
    previous_values: dict[str, str | bool | None],
    current_user: User,
    requested_updates: dict,
) -> list[str]:
    field_labels = {
        "username": "Username",
        "email": "Email",
        "display_name": "Display name",
        "role": "Role",
        "is_active": "Status",
        "department_name": "Department",
        "department_id": "Department",
        "department_admin_email": "Department admin email",
        "organization_name": "Organization",
        "organization_description": "Organization description",
        "country": "Country",
    }
    details: list[str] = []
    seen_labels: set[str] = set()

    for key in requested_updates:
        if key == "password":
            continue
        label = field_labels.get(key)
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)

        if key == "role":
            before_value = _friendly_role_name(previous_values.get("role"))
            after_value = _friendly_role_name(current_user.role)
        elif key == "is_active":
            before_value = "Active" if previous_values.get("is_active") else "Inactive"
            after_value = "Active" if current_user.is_active else "Inactive"
        elif key in {"department_name", "department_id"}:
            before_value = str(previous_values.get("department_name") or "-")
            after_value = str(current_user.department_name or "-")
        elif key == "organization_name":
            before_value = str(previous_values.get("organization_name") or "-")
            after_value = str(requested_updates.get("organization_name") or previous_values.get("organization_name") or "-")
        else:
            before_value = str(previous_values.get(key) or "-")
            after_value = str(getattr(current_user, key, None) or requested_updates.get(key) or "-")

        details.append(f"{label}: {before_value} -> {after_value}")

    return details or ["Profile information updated."]


async def _resolve_existing_user_for_create(
    session: DbSession,
    *,
    username: str,
    email: str | None,
) -> User | None:
    identity_candidates = {username.lower()}
    if email:
        identity_candidates.add(email.lower())
    elif "@" in username:
        identity_candidates.add(username.lower())

    existing = (
        await session.exec(
            select(User).where(
                User.deleted_at.is_(None),
                or_(
                    func.lower(User.username).in_(list(identity_candidates)),
                    func.lower(func.coalesce(User.email, "")).in_(list(identity_candidates)),
                ),
            )
        )
    ).all()
    if existing:
        existing.sort(
            key=lambda user: (
                1 if normalize_role(getattr(user, "role", "consumer")) != "consumer" else 0,
                getattr(user, "updated_at", None) or getattr(user, "create_at", None),
            ),
            reverse=True,
        )
        return existing[0]

    # If admin provided a local-part username (e.g. "deptadmin2"), try reusing
    # a single existing consumer identity like "deptadmin2@company.com".
    if "@" not in username:
        local_part = username.lower()
        consumer_candidates = (
            await session.exec(
                select(User).where(
                    User.deleted_at.is_(None),
                    func.lower(User.role) == "consumer",
                )
            )
        ).all()
        local_part_matches = []
        for candidate in consumer_candidates:
            username_local = (candidate.username or "").strip().lower().split("@", 1)[0]
            email_local = (candidate.email or "").strip().lower().split("@", 1)[0]
            if local_part and (username_local == local_part or email_local == local_part):
                local_part_matches.append(candidate)
        if len(local_part_matches) == 1:
            return local_part_matches[0]

    # Fallback: look for a soft-deleted user with the same username so the
    # caller can reactivate it instead of failing on a unique-constraint error.
    soft_deleted = (
        await session.exec(
            select(User).where(
                User.deleted_at.is_not(None),
                func.lower(User.username) == username.lower(),
            )
        )
    ).first()
    if soft_deleted:
        return soft_deleted

    return None


async def _assignable_roles_for_creator(session: DbSession, creator_role: str) -> list[str]:
    role_rows = (
        await session.exec(
            select(Role).where(Role.is_active.is_(True)).order_by(Role.name)
        )
    ).all()
    global_role_names = [normalize_role(role.name) for role in role_rows]

    if creator_role == "root":
        return [role for role in global_role_names if role == "super_admin"]

    if creator_role == "super_admin":
        return [
            role
            for role in global_role_names
            if role not in {"root", "super_admin", *NON_ASSIGNABLE_ROLES}
        ]

    if creator_role == "department_admin":
        return [
            role
            for role in global_role_names
            if role not in {"root", "super_admin", "department_admin", *NON_ASSIGNABLE_ROLES, *ORG_SCOPED_NON_DEPARTMENT_ROLES}
        ]

    return []


async def _get_role_entity(session: DbSession, role_name: str) -> Role:
    normalized = normalize_role(role_name)
    role = (await session.exec(select(Role).where(Role.name == normalized))).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Role '{normalized}' is not configured.")
    return role


async def _get_admin_org_ids(session: DbSession, current_user: User) -> set[UUID]:
    if normalize_role(current_user.role) == "root":
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


async def _get_admin_department_ids(session: DbSession, current_user: User) -> set[UUID]:
    rows = (
        await session.exec(
            select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
            )
        )
    ).all()
    return set(rows)


async def _resolve_creator_org(
    session: DbSession,
    current_user: User,
    organization_name: str | None,
) -> UUID:
    org_ids = await _get_admin_org_ids(session, current_user)
    if not org_ids:
        raise HTTPException(status_code=400, detail="Creator has no organization membership.")

    if len(org_ids) == 1 and not organization_name:
        return next(iter(org_ids))

    if not organization_name:
        raise HTTPException(status_code=400, detail="Organization name is required.")

    normalized_name = _normalize_name_key(organization_name)
    org = (
        await session.exec(
            select(Organization).where(
                Organization.id.in_(list(org_ids)),
                func.lower(func.trim(Organization.name)) == normalized_name,
            )
        )
    ).first()
    if not org:
        raise HTTPException(status_code=400, detail="Invalid organization name.")
    return org.id


async def _ensure_org_membership(
    session: DbSession,
    *,
    user_id: UUID,
    org_id: UUID,
    role_id: UUID,
    actor_user_id: UUID,
) -> None:
    existing = (
        await session.exec(
            select(UserOrganizationMembership).where(
                UserOrganizationMembership.user_id == user_id,
                UserOrganizationMembership.org_id == org_id,
            )
        )
    ).first()
    if existing:
        existing.role_id = role_id
        existing.status = "active"
        existing.updated_at = datetime.now(timezone.utc)
        existing.accepted_at = existing.accepted_at or datetime.now(timezone.utc)
        session.add(existing)
        return

    session.add(
        UserOrganizationMembership(
            user_id=user_id,
            org_id=org_id,
            status="active",
            role_id=role_id,
            invited_by=actor_user_id,
            accepted_at=datetime.now(timezone.utc),
        )
    )


async def _ensure_department_membership(
    session: DbSession,
    *,
    user_id: UUID,
    org_id: UUID,
    department_id: UUID,
    role_id: UUID,
    actor_user_id: UUID,
) -> None:
    existing = (
        await session.exec(
            select(UserDepartmentMembership).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.org_id == org_id,
                UserDepartmentMembership.department_id == department_id,
            )
        )
    ).first()
    if existing:
        existing.role_id = role_id
        existing.status = ACTIVE_DEPT_STATUS
        existing.updated_at = datetime.now(timezone.utc)
        existing.assigned_at = existing.assigned_at or datetime.now(timezone.utc)
        session.add(existing)
        return

    session.add(
        UserDepartmentMembership(
            user_id=user_id,
            org_id=org_id,
            department_id=department_id,
            status=ACTIVE_DEPT_STATUS,
            role_id=role_id,
            assigned_by=actor_user_id,
            assigned_at=datetime.now(timezone.utc),
        )
    )


async def _visible_user_ids_for_admin(session: DbSession, current_user: User) -> set[UUID]:
    role = normalize_role(current_user.role)
    if role == "root":
        return set((await session.exec(select(User.id).where(User.id != current_user.id))).all())

    if role == "super_admin":
        org_ids = await _get_admin_org_ids(session, current_user)
        if not org_ids:
            return set()
        rows = (
            await session.exec(
                select(distinct(UserOrganizationMembership.user_id)).where(
                    UserOrganizationMembership.org_id.in_(list(org_ids)),
                    UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                )
            )
        ).all()
        return set(rows) - {current_user.id}

    if role == "department_admin":
        dept_ids = await _get_admin_department_ids(session, current_user)
        if not dept_ids:
            return set()
        rows = (
            await session.exec(
                select(distinct(UserDepartmentMembership.user_id)).where(
                    UserDepartmentMembership.department_id.in_(list(dept_ids)),
                    UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                )
            )
        ).all()
        return set(rows) - {current_user.id}

    return set()


async def _is_target_visible_to_admin(
    session: DbSession,
    *,
    current_user: User,
    target_user_id: UUID,
) -> bool:
    role = normalize_role(current_user.role)
    if role == "root":
        return target_user_id != current_user.id

    if role == "super_admin":
        org_ids = await _get_admin_org_ids(session, current_user)
        if not org_ids:
            return False
        return bool(
            (
                await session.exec(
                    select(exists().where(
                        UserOrganizationMembership.user_id == target_user_id,
                        UserOrganizationMembership.org_id.in_(list(org_ids)),
                        UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                    ))
                )
            ).one()
        )

    if role == "department_admin":
        dept_ids = await _get_admin_department_ids(session, current_user)
        if not dept_ids:
            return False
        return bool(
            (
                await session.exec(
                    select(exists().where(
                        UserDepartmentMembership.user_id == target_user_id,
                        UserDepartmentMembership.department_id.in_(list(dept_ids)),
                        UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                    ))
                )
            ).one()
        )

    return False


async def _target_belongs_to_department(session: DbSession, target_user: User) -> bool:
    """True if the user already has an active membership in any department.

    Used to block promoting an existing department member to department_admin —
    they were created under another admin, and promotion would leave them with
    the role but no department to admin (control panel etc. show nothing).
    """
    return bool(
        (
            await session.exec(
                select(exists().where(
                    UserDepartmentMembership.user_id == target_user.id,
                    UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                ))
            )
        ).one()
    )


async def _target_has_managed_users(session: DbSession, target_user: User) -> bool:
    role = normalize_role(target_user.role)

    if role == "super_admin":
        org_ids = await _get_admin_org_ids(session, target_user)
        if not org_ids:
            return False
        return bool(
            (
                await session.exec(
                    select(exists().where(
                        UserOrganizationMembership.org_id.in_(list(org_ids)),
                        UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                        UserOrganizationMembership.user_id != target_user.id,
                    ))
                )
            ).one()
        )

    if role == "department_admin":
        dept_ids = await _get_admin_department_ids(session, target_user)
        if not dept_ids:
            return False
        return bool(
            (
                await session.exec(
                    select(exists().where(
                        UserDepartmentMembership.department_id.in_(list(dept_ids)),
                        UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                        UserDepartmentMembership.user_id != target_user.id,
                    ))
                )
            ).one()
        )

    return False


async def _super_admin_subordinate_department_admin_ids(
    session: DbSession,
    *,
    target_user: User,
) -> list[UUID]:
    org_ids = await _get_admin_org_ids(session, target_user)
    if not org_ids:
        return []

    return list(
        (
            await session.exec(
                select(distinct(User.id))
                .join(
                    UserOrganizationMembership,
                    UserOrganizationMembership.user_id == User.id,
                )
                .where(
                    User.deleted_at.is_(None),
                    User.id != target_user.id,
                    UserOrganizationMembership.org_id.in_(list(org_ids)),
                    UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                    func.lower(User.role) == "department_admin",
                )
            )
        ).all()
    )


async def _get_super_admin_delete_blocker(
    session: DbSession,
    *,
    target_user: User,
) -> str | None:
    subordinate_dept_admin_ids = await _super_admin_subordinate_department_admin_ids(
        session,
        target_user=target_user,
    )
    if not subordinate_dept_admin_ids:
        return None

    subordinate_dept_admins = (
        await session.exec(
            select(User).where(User.id.in_(subordinate_dept_admin_ids))
        )
    ).all()

    blocking_admins: list[str] = []
    for dept_admin in subordinate_dept_admins:
        if await _target_has_managed_users(session, dept_admin):
            blocking_admins.append(
                _strip_or_none(dept_admin.display_name)
                or _strip_or_none(dept_admin.username)
                or str(dept_admin.id)
            )

    if not blocking_admins:
        return None

    blockers = ", ".join(sorted(blocking_admins))
    return (
        "This super admin cannot be deleted because these department admins still "
        f"have users under them: {blockers}."
    )


async def _owned_agent_ids_for_user(session: DbSession, user_id: UUID) -> list[UUID]:
    return list(
        (
            await session.exec(
                select(Agent.id).where(
                    Agent.user_id == user_id,
                )
            )
        ).all()
    )


async def _active_runtime_dependency_counts(
    session: DbSession,
    *,
    user_id: UUID,
) -> tuple[int, int]:
    uat_count = int(
        (
            await session.exec(
                select(func.count())
                .select_from(AgentDeploymentUAT)
                .join(Agent, Agent.id == AgentDeploymentUAT.agent_id)
                .where(
                    Agent.user_id == user_id,
                    AgentDeploymentUAT.is_active.is_(True),
                )
            )
        ).one()
        or 0
    )
    prod_count = int(
        (
            await session.exec(
                select(func.count())
                .select_from(AgentDeploymentProd)
                .join(Agent, Agent.id == AgentDeploymentProd.agent_id)
                .where(
                    Agent.user_id == user_id,
                    AgentDeploymentProd.is_active.is_(True),
                )
            )
        ).one()
        or 0
    )
    return uat_count, prod_count


async def _published_deployment_counts_for_user(
    session: DbSession,
    *,
    user_id: UUID,
) -> tuple[int, int]:
    uat_count = int(
        (
            await session.exec(
                select(func.count())
                .select_from(AgentDeploymentUAT)
                .join(Agent, Agent.id == AgentDeploymentUAT.agent_id)
                .where(
                    Agent.user_id == user_id,
                    AgentDeploymentUAT.status == DeploymentUATStatusEnum.PUBLISHED,
                )
            )
        ).one()
        or 0
    )
    prod_count = int(
        (
            await session.exec(
                select(func.count())
                .select_from(AgentDeploymentProd)
                .join(Agent, Agent.id == AgentDeploymentProd.agent_id)
                .where(
                    Agent.user_id == user_id,
                    AgentDeploymentProd.status == DeploymentPRODStatusEnum.PUBLISHED,
                )
            )
        ).one()
        or 0
    )
    return uat_count, prod_count


async def _can_current_admin_delete_target_user(
    session: DbSession,
    *,
    current_user: User,
    target_user: User,
) -> None:
    current_role = normalize_role(current_user.role)
    if current_role == "root":
        return

    if not await _is_target_visible_to_admin(
        session,
        current_user=current_user,
        target_user_id=target_user.id,
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    if current_role == "department_admin":
        target_role = normalize_role(target_user.role)
        if target_role in {"root", "super_admin"}:
            raise HTTPException(status_code=403, detail="Permission denied")
        return

    if current_role == "super_admin":
        target_role = normalize_role(target_user.role)
        if target_role in {"root", "super_admin"}:
            raise HTTPException(status_code=403, detail="Permission denied")
        return

    if target_user.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="You can delete only users you created.")


async def _get_delete_user_blocker(
    session: DbSession,
    *,
    target_user: User,
) -> str | None:
    target_role = normalize_role(target_user.role)

    if target_role == "super_admin":
        super_admin_blocker = await _get_super_admin_delete_blocker(
            session,
            target_user=target_user,
        )
        if super_admin_blocker:
            return super_admin_blocker

    if target_role == "department_admin" and await _target_has_managed_users(
        session,
        target_user,
    ):
        return (
            "This department admin still has users under them. "
            "Delete or reassign those users first, then delete this account."
        )

    active_uat_count, active_prod_count = await _active_runtime_dependency_counts(
        session,
        user_id=target_user.id,
    )
    if active_uat_count or active_prod_count:
        return "User deletion is not possible due to active UAT/PROD agents."

    return None


async def _hard_delete_user_dependencies(
    session: DbSession,
    *,
    target_user: User,
    actor_user_id: UUID,
) -> None:
    user_id = target_user.id
    await invalidate_user_auth(
        user_id,
        email=target_user.email or target_user.username,
        entra_object_id=target_user.entra_object_id,
    )

    # Transfer department / organization ownership to the acting admin so the user row can be deleted.
    await session.exec(
        update(Department)
        .where(Department.admin_user_id == user_id)
        .values(admin_user_id=actor_user_id, updated_by=actor_user_id)
    )
    await session.exec(
        update(Department)
        .where(Department.created_by == user_id)
        .values(created_by=actor_user_id)
    )
    await session.exec(
        update(Department)
        .where(Department.updated_by == user_id)
        .values(updated_by=actor_user_id)
    )
    await session.exec(
        update(Organization)
        .where(Organization.owner_user_id == user_id)
        .values(owner_user_id=actor_user_id, updated_by=actor_user_id)
    )
    await session.exec(
        update(Organization)
        .where(Organization.created_by == user_id)
        .values(created_by=actor_user_id)
    )
    await session.exec(
        update(Organization)
        .where(Organization.updated_by == user_id)
        .values(updated_by=actor_user_id)
    )

    # Clear self-references from remaining users.
    await session.exec(
        update(User)
        .where(User.created_by == user_id)
        .values(created_by=None)
    )
    await session.exec(
        update(User)
        .where(User.department_admin == user_id)
        .values(department_admin=None, department_admin_email=None)
    )

    # Clear nullable references in membership tables.
    await session.exec(
        update(UserDepartmentMembership)
        .where(UserDepartmentMembership.assigned_by == user_id)
        .values(assigned_by=None)
    )
    await session.exec(
        update(UserOrganizationMembership)
        .where(UserOrganizationMembership.invited_by == user_id)
        .values(invited_by=None)
    )

    await _hard_delete_user_assets(
        session,
        target_user=target_user,
    )

    await session.exec(delete(UserDepartmentMembership).where(UserDepartmentMembership.user_id == user_id))
    await session.exec(delete(UserOrganizationMembership).where(UserOrganizationMembership.user_id == user_id))

    await session.delete(target_user)


async def _hard_delete_user_assets(
    session: DbSession,
    *,
    target_user: User,
) -> None:
    user_id = target_user.id
    agent_ids = await _owned_agent_ids_for_user(session, user_id)
    uat_deployment_ids: list[UUID] = []

    if agent_ids:
        uat_deployment_ids = list(
            (
                await session.exec(
                    select(AgentDeploymentUAT.id).where(
                        AgentDeploymentUAT.agent_id.in_(agent_ids),
                    )
                )
            ).all()
        )

    has_control_panel_uat = await _table_exists(session, "control_panel_uat")
    has_publish_record = await _table_exists(session, "publish_record")

    if uat_deployment_ids and has_control_panel_uat:
        control_panel_uat_table = table("control_panel_uat", column("deployment_id"))
        await session.execute(
            delete(control_panel_uat_table).where(
                control_panel_uat_table.c.deployment_id.in_(uat_deployment_ids)
            )
        )

    if agent_ids:
        trigger_config_table = table(
            "trigger_config",
            column("id"),
            column("agent_id"),
        )
        trigger_execution_log_table = table(
            "trigger_execution_log",
            column("trigger_config_id"),
        )
        trigger_config_ids = list(
            (
                await session.execute(
                    select(trigger_config_table.c.id).where(
                        trigger_config_table.c.agent_id.in_(agent_ids)
                    )
                )
            ).scalars().all()
        )
        if trigger_config_ids:
            await session.execute(
                delete(trigger_execution_log_table).where(
                    trigger_execution_log_table.c.trigger_config_id.in_(trigger_config_ids)
                )
            )
        await session.execute(
            delete(trigger_config_table).where(
                trigger_config_table.c.agent_id.in_(agent_ids)
            )
        )

        await session.exec(delete(ApprovalRequest).where(ApprovalRequest.agent_id.in_(agent_ids)))
        if has_publish_record:
            publish_record_table = table("publish_record", column("agent_id"))
            await session.execute(
                delete(publish_record_table).where(
                    publish_record_table.c.agent_id.in_(agent_ids)
                )
            )
        await session.exec(delete(AgentRegistryRating).where(AgentRegistryRating.registry_id.in_(
            select(AgentRegistry.id).where(AgentRegistry.agent_id.in_(agent_ids))
        )))
        await session.exec(delete(AgentRegistry).where(AgentRegistry.agent_id.in_(agent_ids)))
        await session.exec(delete(AgentPublishRecipient).where(AgentPublishRecipient.agent_id.in_(agent_ids)))
        await session.exec(delete(AgentBundle).where(AgentBundle.agent_id.in_(agent_ids)))
        await session.exec(delete(AgentApiKey).where(AgentApiKey.agent_id.in_(agent_ids)))
        await session.exec(delete(AgentEditLock).where(AgentEditLock.agent_id.in_(agent_ids)))
        await session.exec(delete(AgentDeploymentProd).where(AgentDeploymentProd.agent_id.in_(agent_ids)))
        await session.exec(delete(AgentDeploymentUAT).where(AgentDeploymentUAT.agent_id.in_(agent_ids)))
        await session.exec(delete(Agent).where(Agent.id.in_(agent_ids)))

    knowledge_base_table = table("knowledge_base", column("id"), column("created_by"))
    knowledge_base_ids = list(
        (
            await session.execute(
                select(knowledge_base_table.c.id).where(
                    knowledge_base_table.c.created_by == user_id
                )
            )
        ).scalars().all()
    )
    if knowledge_base_ids:
        await session.exec(delete(File).where(File.knowledge_base_id.in_(knowledge_base_ids)))
        await session.execute(
            delete(knowledge_base_table).where(
                knowledge_base_table.c.id.in_(knowledge_base_ids)
            )
        )

    model_registry_table = table("model_registry", column("id"), column("created_by_id"))
    model_ids = list(
        (
            await session.execute(
                select(model_registry_table.c.id).where(
                    model_registry_table.c.created_by_id == user_id
                )
            )
        ).scalars().all()
    )
    if model_ids:
        model_approval_request_table = table("model_approval_request", column("model_id"))
        model_audit_log_table = table("model_audit_log", column("model_id"))
        await session.execute(
            delete(model_approval_request_table).where(
                model_approval_request_table.c.model_id.in_(model_ids)
            )
        )
        await session.execute(
            delete(model_audit_log_table).where(
                model_audit_log_table.c.model_id.in_(model_ids)
            )
        )
        guardrail_catalogue_table = table("guardrail_catalogue", column("model_registry_id"))
        await session.execute(
            delete(guardrail_catalogue_table).where(
                guardrail_catalogue_table.c.model_registry_id.in_(model_ids)
            )
        )
        await session.execute(
            delete(model_registry_table).where(
                model_registry_table.c.id.in_(model_ids)
            )
        )

    mcp_registry_table = table("mcp_registry", column("id"), column("created_by_id"))
    mcp_ids = list(
        (
            await session.execute(
                select(mcp_registry_table.c.id).where(
                    mcp_registry_table.c.created_by_id == user_id
                )
            )
        ).scalars().all()
    )
    if mcp_ids:
        mcp_approval_request_table = table("mcp_approval_request", column("mcp_id"))
        mcp_audit_log_table = table("mcp_audit_log", column("mcp_id"))
        await session.execute(
            delete(mcp_approval_request_table).where(
                mcp_approval_request_table.c.mcp_id.in_(mcp_ids)
            )
        )
        await session.execute(
            delete(mcp_audit_log_table).where(
                mcp_audit_log_table.c.mcp_id.in_(mcp_ids)
            )
        )
        await session.execute(
            delete(mcp_registry_table).where(
                mcp_registry_table.c.id.in_(mcp_ids)
            )
        )

    connector_catalogue_table = table("connector_catalogue", column("created_by"))
    await session.execute(
        delete(connector_catalogue_table).where(
            connector_catalogue_table.c.created_by == user_id
        )
    )

    vector_db_catalogue_table = table("vector_db_catalogue", column("created_by"))
    await session.execute(
        delete(vector_db_catalogue_table).where(
            vector_db_catalogue_table.c.created_by == user_id
        )
    )

    evaluator_table = table("evaluator", column("user_id"))
    await session.execute(
        delete(evaluator_table).where(
            evaluator_table.c.user_id == user_id
        )
    )

    package_request_table = table("package_request", column("requested_by"))
    await session.execute(
        delete(package_request_table).where(
            package_request_table.c.requested_by == user_id
        )
    )

    # Remove direct user-owned rows / references.
    await session.exec(delete(AgentEditLock).where(AgentEditLock.locked_by == user_id))
    await session.exec(delete(AgentApiKey).where(AgentApiKey.created_by == user_id))
    await session.exec(delete(AgentBundle).where(AgentBundle.created_by == user_id))
    await session.exec(delete(AgentPublishRecipient).where(AgentPublishRecipient.recipient_user_id == user_id))
    await session.exec(delete(AgentPublishRecipient).where(AgentPublishRecipient.created_by == user_id))
    await session.exec(delete(AgentRegistryRating).where(AgentRegistryRating.user_id == user_id))
    await session.exec(delete(File).where(File.user_id == user_id))
    await session.exec(delete(Project).where(Project.user_id == user_id))


async def _ensure_langfuse_org_admin_binding(
    session: DbSession,
    *,
    org: Organization,
    actor: User,
) -> None:
    """Idempotently provision the Langfuse org + admin project for an AgentCore org.

    Safe to call from any code path that creates or reuses an Organization
    (add_user, patch_user, etc.). The underlying service short-circuits if a
    binding already exists, so repeated calls are no-ops.
    """
    try:
        provisioning_service = get_langfuse_provisioning_service()
        if provisioning_service.enabled:
            await provisioning_service.provision_org_admin_project(
                session,
                org=org,
                actor=actor,
            )
    except LangfuseProvisioningError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Langfuse provisioning failed; organization change rolled back: {exc}",
        ) from exc


async def _ensure_langfuse_department_binding(
    session: DbSession,
    *,
    org: Organization,
    department: Department,
    actor: User,
) -> None:
    """Idempotently provision the Langfuse project for an AgentCore department.

    Safe to call from any code path that creates or reuses a Department.
    """
    try:
        provisioning_service = get_langfuse_provisioning_service()
        if provisioning_service.enabled:
            await provisioning_service.provision_department_project(
                session,
                org=org,
                department=department,
                actor=actor,
            )
    except LangfuseProvisioningError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Langfuse provisioning failed; department change rolled back: {exc}",
        ) from exc


@router.post("/", response_model=UserRead, status_code=201)
async def add_user(
    user: UserCreate,
    response: Response,
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> User:
    """Add a new user to the database and stitch org/dept memberships by creator role."""
    try:
        username = _normalize_identity(user.username)
        if not username:
            raise HTTPException(status_code=400, detail="Username cannot be empty.")

        email = _normalize_identity(user.email)
        display_name = _strip_or_none(user.display_name)
        department_name = _strip_or_none(user.department_name)
        organization_name = _strip_or_none(user.organization_name)
        organization_description = _strip_or_none(user.organization_description)
        country = _strip_or_none(user.country)
        creator_role = normalize_role(getattr(current_user, "role", "developer"))
        target_role = normalize_role(user.role)
        assignable_roles = await _assignable_roles_for_creator(session, creator_role)

        existing_user = await _resolve_existing_user_for_create(
            session,
            username=username,
            email=email,
        )
        is_reusing_soft_deleted = bool(
            existing_user and existing_user.deleted_at is not None
        )
        is_reusing_consumer = bool(
            existing_user
            and not is_reusing_soft_deleted
            and normalize_role(getattr(existing_user, "role", "consumer")) == "consumer"
        )
        is_reusing_same_role = bool(
            existing_user
            and not is_reusing_consumer
            and not is_reusing_soft_deleted
            and normalize_role(getattr(existing_user, "role", "consumer")) == target_role
        )
        if existing_user and not is_reusing_consumer and not is_reusing_same_role and not is_reusing_soft_deleted:
            raise HTTPException(status_code=400, detail="This username is unavailable.")

        raw_password = user.password or secrets.token_urlsafe(32)
        if (is_reusing_consumer or is_reusing_same_role or is_reusing_soft_deleted) and existing_user:
            new_user = existing_user
            if is_reusing_soft_deleted:
                new_user.deleted_at = None
                new_user.is_active = user.is_active if user.is_active is not None else True
            new_user.display_name = display_name or new_user.display_name
            new_user.email = new_user.email or email or username
        else:
            user_payload = user.model_dump()
            user_payload["username"] = username
            user_payload["email"] = email
            user_payload["display_name"] = display_name
            user_payload["department_name"] = department_name
            user_payload["organization_name"] = organization_name
            user_payload["organization_description"] = organization_description
            user_payload["country"] = country
            user_payload["password"] = raw_password
            new_user = User.model_validate(user_payload, from_attributes=True)

        creator_email = getattr(current_user, "username", None)
        new_user.creator_email = creator_email
        new_user.creator_role = creator_role
        new_user.created_by = current_user.id
        new_user.role = target_role

        if target_role not in assignable_roles:
            raise HTTPException(status_code=403, detail="Selected role is not assignable by current user.")

        if creator_role == "root" and not organization_name:
            raise HTTPException(status_code=400, detail="Organization name is required.")

        if creator_role not in {"root", "super_admin", "department_admin"}:
            raise HTTPException(status_code=403, detail="Only admins can create users.")

        new_user.password = get_password_hash(raw_password)
        new_user.is_superuser = new_user.role in {"super_admin", "department_admin", "root"}
        new_user.is_active = (
            user.is_active
            if user.is_active is not None
            else get_settings_service().auth_settings.NEW_USER_IS_ACTIVE
        )
        session.add(new_user)
        await session.flush()

        role_entity = await _get_role_entity(session, target_role)

        if creator_role == "root":
            # Reactivate a suspended/deleted org with the same name if one exists
            # (e.g. after a super_admin was deleted and is being recreated).
            org = await _find_organization_by_normalized_name(session, organization_name)
            if org:
                org.status = "active"
                org.owner_user_id = new_user.id
                org.description = organization_description or org.description
                org.updated_by = current_user.id
                org.updated_at = datetime.now(timezone.utc)
                session.add(org)
            else:
                org = Organization(
                    name=organization_name,
                    description=organization_description,
                    status="active",
                    owner_user_id=new_user.id,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
                session.add(org)
            await session.flush()
            await _ensure_org_membership(
                session,
                user_id=new_user.id,
                org_id=org.id,
                role_id=role_entity.id,
                actor_user_id=current_user.id,
            )
            root_role = await _get_role_entity(session, "root")
            await _ensure_org_membership(
                session,
                user_id=current_user.id,
                org_id=org.id,
                role_id=root_role.id,
                actor_user_id=current_user.id,
            )
            await _ensure_langfuse_org_admin_binding(
                session,
                org=org,
                actor=current_user,
            )

        elif creator_role == "super_admin":
            org_id = await _resolve_creator_org(session, current_user, organization_name)
            org = await session.get(Organization, org_id)
            if not org:
                raise HTTPException(status_code=400, detail="Invalid organization mapping.")
            await _ensure_org_membership(
                session,
                user_id=new_user.id,
                org_id=org_id,
                role_id=role_entity.id,
                actor_user_id=current_user.id,
            )

            if target_role == "department_admin":
                if not department_name:
                    raise HTTPException(status_code=400, detail="Department name is required for department admins.")
                _ensure_department_name_differs_from_org(
                    department_name=department_name,
                    organization_name=org.name if org else organization_name,
                )
                # Reactivate an archived department with the same name if one exists
                # (e.g. after a dept_admin was deleted and is being recreated).
                department = await _find_department_by_normalized_name(
                    session,
                    org_id=org_id,
                    department_name=department_name,
                )
                if department:
                    department.status = "active"
                    department.admin_user_id = new_user.id
                    department.updated_by = current_user.id
                    department.updated_at = datetime.now(timezone.utc)
                    session.add(department)
                else:
                    department = Department(
                        org_id=org_id,
                        name=department_name,
                        admin_user_id=new_user.id,
                        status="active",
                        created_by=current_user.id,
                        updated_by=current_user.id,
                    )
                    session.add(department)
                await session.flush()
                new_user.department_name = department.name
                new_user.department_admin_email = None
                await _ensure_department_membership(
                    session,
                    user_id=new_user.id,
                    org_id=org_id,
                    department_id=department.id,
                    role_id=role_entity.id,
                    actor_user_id=current_user.id,
                )
                await _ensure_langfuse_department_binding(
                    session,
                    org=org,
                    department=department,
                    actor=current_user,
                )
            else:
                if target_role in ORG_SCOPED_NON_DEPARTMENT_ROLES:
                    new_user.department_admin_email = None
                    new_user.department_name = None
                elif target_role in {"developer", "business_user"}:
                    if not user.department_id:
                        raise HTTPException(status_code=400, detail="Department is required.")
                    department = (
                        await session.exec(
                            select(Department).where(
                                Department.id == user.department_id,
                                Department.org_id == org_id,
                                Department.status == "active",
                            )
                        )
                    ).first()
                    if not department:
                        raise HTTPException(status_code=400, detail="Invalid department.")
                    dept_admin = await session.get(User, department.admin_user_id)
                    new_user.department_admin_email = dept_admin.username if dept_admin else None
                    new_user.department_name = department.name
                    await _ensure_department_membership(
                        session,
                        user_id=new_user.id,
                        org_id=org_id,
                        department_id=department.id,
                        role_id=role_entity.id,
                        actor_user_id=current_user.id,
                    )
                else:
                    raise HTTPException(status_code=400, detail="Invalid target role for super admin.")

        elif creator_role == "department_admin":
            creator_membership = (
                await session.exec(
                    select(UserDepartmentMembership).where(
                        UserDepartmentMembership.user_id == current_user.id,
                        UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                    )
                )
            ).first()
            if not creator_membership:
                raise HTTPException(status_code=400, detail="Department admin is missing membership mapping.")
            department = await session.get(Department, creator_membership.department_id)
            new_user.department_admin_email = current_user.username
            new_user.department_name = department.name if department else None
            await _ensure_org_membership(
                session,
                user_id=new_user.id,
                org_id=creator_membership.org_id,
                role_id=role_entity.id,
                actor_user_id=current_user.id,
            )
            await _ensure_department_membership(
                session,
                user_id=new_user.id,
                org_id=creator_membership.org_id,
                department_id=creator_membership.department_id,
                role_id=role_entity.id,
                actor_user_id=current_user.id,
            )

        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        settings = get_settings_service().settings
        email_sent, email_detail = await send_user_notification_email(
            settings=settings,
            recipient_email=_notification_recipient_for_user(new_user),
            recipient_name=_display_name_for_user(new_user),
            subject="Your AgentCore account has been created",
            headline="Your AgentCore account is ready",
            intro_text="Your account has been created or reactivated in AgentCore.",
            summary_text="You are receiving this email because an administrator created or updated your access.",
            actor_name=_display_name_for_user(current_user),
            changed_fields=_build_add_user_email_details(new_user),
            organization_name=organization_name,
            department_name=new_user.department_name,
        )
        _format_notification_email_status(
            response,
            sent=email_sent,
            detail=email_detail,
        )

    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as e:
        await session.rollback()
        error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
        if "username" in error_msg.lower():
            detail = "This username is unavailable."
        elif "email" in error_msg.lower():
            detail = "This email is already in use."
        elif "organization" in error_msg.lower() or "ix_organization_name" in error_msg.lower():
            detail = "An organization with this name already exists."
        elif "department" in error_msg.lower() or "uq_department" in error_msg.lower():
            detail = "A department with this name already exists in the organization."
        else:
            detail = "Could not create user due to a data conflict."
        raise HTTPException(status_code=400, detail=detail) from e
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e

    return new_user


@router.get("/assignable-roles", response_model=list[str])
async def list_assignable_roles(
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> list[str]:
    creator_role = normalize_role(getattr(current_user, "role", "developer"))
    return await _assignable_roles_for_creator(session, creator_role)


@router.get("/departments")
async def list_visible_departments(
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> list[dict]:
    current_role = normalize_role(current_user.role)
    if current_role == "root":
        depts = (await session.exec(select(Department).order_by(Department.name.asc()))).all()
    elif current_role == "super_admin":
        org_ids = await _get_admin_org_ids(session, current_user)
        if not org_ids:
            return []
        depts = (
            await session.exec(
                select(Department)
                .where(
                    Department.org_id.in_(list(org_ids)),
                    Department.status == "active",
                )
                .order_by(Department.name.asc())
            )
        ).all()
    elif current_role == "department_admin":
        dept_ids = await _get_admin_department_ids(session, current_user)
        if not dept_ids:
            return []
        depts = (
            await session.exec(
                select(Department)
                .where(
                    Department.id.in_(list(dept_ids)),
                    Department.status == "active",
                )
                .order_by(Department.name.asc())
            )
        ).all()
    else:
        return []

    return [{"id": str(dept.id), "name": dept.name, "org_id": str(dept.org_id)} for dept in depts]


@router.get("/organizations")
async def list_visible_organizations(
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> list[dict]:
    current_role = normalize_role(current_user.role)
    if current_role == "root":
        orgs = (await session.exec(select(Organization).order_by(Organization.name.asc()))).all()
    else:
        org_ids = await _get_admin_org_ids(session, current_user)
        if not org_ids:
            return []
        orgs = (
            await session.exec(
                select(Organization)
                .where(
                    Organization.id.in_(list(org_ids)),
                    Organization.status == "active",
                )
                .order_by(Organization.name.asc())
            )
        ).all()

    return [{"id": str(org.id), "name": org.name, "status": org.status} for org in orgs]


@router.get("/whoami", response_model=UserReadWithPermissions)
async def read_current_user(
    current_user: CurrentActiveUser,
    db: DbSession,
) -> dict:
    """Retrieve the current user's data."""
    settings_service = get_settings_service()
    user_cache = UserCacheService(settings_service)

    try:
        cached_user = await user_cache.get_user(str(current_user.id))
        if not cached_user:
            user = await get_user_by_id(db, current_user.id)
            cached_user = user.model_dump()
            await user_cache.set_user(cached_user)
    except Exception:
        cached_user = current_user.model_dump()

    try:
        if permission_cache:
            user_permissions = await permission_cache.get_permissions_for_role(current_user.role)
        else:
            user_permissions = await get_permissions_for_role(current_user.role)
    except Exception:
        user_permissions = await get_permissions_for_role(current_user.role)

    if not user_permissions:
        user_permissions = await get_permissions_for_role(current_user.role)

    organization_name = (
        await db.exec(
            select(Organization.name)
            .join(
                UserOrganizationMembership,
                UserOrganizationMembership.org_id == Organization.id,
            )
            .where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
            .order_by(Organization.created_at.asc())
        )
    ).first()
    organization_id = (
        await db.exec(
            select(Organization.id)
            .join(
                UserOrganizationMembership,
                UserOrganizationMembership.org_id == Organization.id,
            )
            .where(
                UserOrganizationMembership.user_id == current_user.id,
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
            .order_by(Organization.created_at.asc())
        )
    ).first()

    department_id = (
        await db.exec(
            select(UserDepartmentMembership.department_id)
            .where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
            )
            .order_by(UserDepartmentMembership.assigned_at.asc())
        )
    ).first()

    return {
        **cached_user,
        "permissions": user_permissions,
        "organization_name": organization_name,
        "organization_id": organization_id,
        "department_id": department_id,
    }


@router.get("/export-csv")
async def export_users_csv(
    *,
    q: str | None = None,
    role: str | None = None,
    organization_id: UUID | None = None,
    department_id: UUID | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: DbSession,
    current_admin: User = Depends(PermissionChecker(["view_admin_page"])),
):
    """Export visible users as a CSV file (respects role-based visibility)."""
    visible_user_ids = await _visible_user_ids_for_admin(session, current_admin)
    if not visible_user_ids:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Username", "Email", "Organization", "Department", "Role", "Active", "Created By", "Created At", "Updated At", "Expires At"])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users_export.csv"},
        )

    query: SelectOfScalar = select(User).where(
        User.id.in_(list(visible_user_ids)),
        User.deleted_at.is_(None),
    )
    if normalize_role(current_admin.role) != "root":
        query = query.where(User.role != "root")
    else:
        duplicate = aliased(User)
        current_identity = func.lower(func.coalesce(User.email, User.username))
        duplicate_identity = func.lower(func.coalesce(duplicate.email, duplicate.username))
        has_non_consumer_duplicate = exists(
            select(1).where(
                duplicate.id != User.id,
                duplicate_identity == current_identity,
                func.lower(duplicate.role) != "consumer",
            )
        )
        query = query.where(
            ~and_(func.lower(User.role) == "consumer", has_non_consumer_duplicate)
        )
    if role:
        query = query.where(User.role == normalize_role(role))
    if q:
        query = query.where(User.username.ilike(f"%{q}%"))
    if organization_id:
        org_exists = exists(
            select(1).where(
                UserOrganizationMembership.user_id == User.id,
                UserOrganizationMembership.org_id == organization_id,
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
        )
        query = query.where(org_exists)
    if department_id:
        dept_exists = exists(
            select(1).where(
                UserDepartmentMembership.user_id == User.id,
                UserDepartmentMembership.department_id == department_id,
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
            )
        )
        query = query.where(dept_exists)

    sort_key = (sort_by or "").strip().lower()
    sort_dir = (sort_order or "asc").strip().lower()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"
    order_func = asc if sort_dir == "asc" else desc

    if sort_key == "username":
        query = query.order_by(order_func(User.username))
    elif sort_key == "role":
        query = query.order_by(order_func(User.role))
    elif sort_key == "created_at":
        query = query.order_by(order_func(User.create_at))
    elif sort_key == "updated_at":
        query = query.order_by(order_func(User.updated_at))
    else:
        query = query.order_by(User.username.asc())

    users = (await session.exec(query)).fetchall()

    user_ids = [user.id for user in users]
    creator_ids = [user.created_by for user in users if user.created_by]

    org_map: dict[UUID, str] = {}
    if user_ids:
        org_rows = (
            await session.exec(
                select(UserOrganizationMembership.user_id, Organization.name)
                .join(Organization, Organization.id == UserOrganizationMembership.org_id)
                .where(
                    UserOrganizationMembership.user_id.in_(user_ids),
                    UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                )
            )
        ).all()
        for uid, org_name in org_rows:
            if uid not in org_map:
                org_map[uid] = org_name

    dept_name_map: dict[UUID, str] = {}
    if user_ids:
        dept_rows = (
            await session.exec(
                select(UserDepartmentMembership.user_id, Department.name)
                .join(Department, Department.id == UserDepartmentMembership.department_id)
                .where(
                    UserDepartmentMembership.user_id.in_(user_ids),
                    UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                )
            )
        ).all()
        for uid, dept_name in dept_rows:
            if uid not in dept_name_map:
                dept_name_map[uid] = dept_name

    creator_map: dict[UUID, str] = {}
    if creator_ids:
        creator_rows = (
            await session.exec(select(User.id, User.username).where(User.id.in_(list(set(creator_ids)))))
        ).all()
        creator_map = {cid: cname for cid, cname in creator_rows}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Username", "Email", "Organization", "Department", "Role", "Active", "Created By", "Created At", "Updated At", "Expires At"])

    for user in users:
        org_name = org_map.get(user.id, "")
        dept_name = dept_name_map.get(user.id) or user.department_name or ""
        created_by = creator_map.get(user.created_by) if user.created_by else (user.creator_email or "")
        created_at = user.create_at.strftime("%Y-%m-%d") if user.create_at else ""
        updated_at = user.updated_at.strftime("%Y-%m-%d") if user.updated_at else ""
        expires_at = ""
        if user.expires_at:
            if isinstance(user.expires_at, str):
                expires_at = user.expires_at[:10]
            else:
                expires_at = user.expires_at.strftime("%Y-%m-%d")

        role_display = (user.role or "").replace("_", " ").title()
        active_status = "Yes" if user.is_active else "No"
        if user.expires_at:
            exp_dt = user.expires_at if not isinstance(user.expires_at, str) else datetime.fromisoformat(user.expires_at.replace("Z", "+00:00"))
            if exp_dt <= datetime.now(timezone.utc):
                active_status = "Expired"

        writer.writerow([
            user.username or "",
            user.email or "",
            org_name,
            dept_name,
            role_display,
            active_status,
            created_by,
            created_at,
            updated_at,
            expires_at,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users_export.csv"},
    )


@router.get("/", response_model=UsersResponse)
async def read_all_users(
    *,
    skip: int = 0,
    limit: int = 10,
    role: str | None = None,
    q: str | None = None,
    organization_id: UUID | None = None,
    department_id: UUID | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: DbSession,
    current_admin: User = Depends(PermissionChecker(["view_admin_page"])),
) -> UsersResponse:
    """Retrieve a list of users from the database with hierarchy-aware visibility."""
    visible_user_ids = await _visible_user_ids_for_admin(session, current_admin)
    if not visible_user_ids:
        return UsersResponse(total_count=0, users=[])

    query: SelectOfScalar = select(User).where(
        User.id.in_(list(visible_user_ids)),
        User.deleted_at.is_(None),
    )
    if normalize_role(current_admin.role) != "root":
        query = query.where(User.role != "root")
    else:
        duplicate = aliased(User)
        current_identity = func.lower(func.coalesce(User.email, User.username))
        duplicate_identity = func.lower(func.coalesce(duplicate.email, duplicate.username))
        has_non_consumer_duplicate = exists(
            select(1).where(
                duplicate.id != User.id,
                duplicate_identity == current_identity,
                func.lower(duplicate.role) != "consumer",
            )
        )
        query = query.where(
            ~and_(func.lower(User.role) == "consumer", has_non_consumer_duplicate)
        )
    if role:
        query = query.where(User.role == normalize_role(role))
    if q:
        query = query.where(User.username.ilike(f"%{q}%"))

    if organization_id:
        org_exists = exists(
            select(1).where(
                UserOrganizationMembership.user_id == User.id,
                UserOrganizationMembership.org_id == organization_id,
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
        )
        query = query.where(org_exists)

    if department_id:
        dept_exists = exists(
            select(1).where(
                UserDepartmentMembership.user_id == User.id,
                UserDepartmentMembership.department_id == department_id,
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
            )
        )
        query = query.where(dept_exists)

    sort_key = (sort_by or "").strip().lower()
    sort_dir = (sort_order or "asc").strip().lower()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"
    order_func = asc if sort_dir == "asc" else desc

    if sort_key:
        if sort_key == "organization":
            org_name_subq = (
                select(Organization.name)
                .join(
                    UserOrganizationMembership,
                    Organization.id == UserOrganizationMembership.org_id,
                )
                .where(
                    UserOrganizationMembership.user_id == User.id,
                    UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                )
                .order_by(Organization.name.asc())
                .limit(1)
                .scalar_subquery()
            )
            query = query.order_by(order_func(org_name_subq), User.username.asc())
        elif sort_key == "department":
            dept_name_subq = (
                select(Department.name)
                .join(
                    UserDepartmentMembership,
                    Department.id == UserDepartmentMembership.department_id,
                )
                .where(
                    UserDepartmentMembership.user_id == User.id,
                    UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                )
                .order_by(Department.name.asc())
                .limit(1)
                .scalar_subquery()
            )
            query = query.order_by(order_func(dept_name_subq), User.username.asc())
        elif sort_key == "username":
            query = query.order_by(order_func(User.username))
        elif sort_key == "role":
            query = query.order_by(order_func(User.role))
        elif sort_key == "created_at":
            query = query.order_by(order_func(User.create_at))
        elif sort_key == "updated_at":
            query = query.order_by(order_func(User.updated_at))

    query = query.offset(skip).limit(limit)
    users = (await session.exec(query)).fetchall()

    count_query = select(func.count(distinct(User.id))).select_from(User).where(
        User.id.in_(list(visible_user_ids)),
        User.deleted_at.is_(None),
    )
    if normalize_role(current_admin.role) != "root":
        count_query = count_query.where(User.role != "root")
    else:
        duplicate = aliased(User)
        current_identity = func.lower(func.coalesce(User.email, User.username))
        duplicate_identity = func.lower(func.coalesce(duplicate.email, duplicate.username))
        has_non_consumer_duplicate = exists(
            select(1).where(
                duplicate.id != User.id,
                duplicate_identity == current_identity,
                func.lower(duplicate.role) != "consumer",
            )
        )
        count_query = count_query.where(
            ~and_(func.lower(User.role) == "consumer", has_non_consumer_duplicate)
        )
    if role:
        count_query = count_query.where(User.role == normalize_role(role))
    if q:
        count_query = count_query.where(User.username.ilike(f"%{q}%"))
    if organization_id:
        org_exists = exists(
            select(1).where(
                UserOrganizationMembership.user_id == User.id,
                UserOrganizationMembership.org_id == organization_id,
                UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
            )
        )
        count_query = count_query.where(org_exists)
    if department_id:
        dept_exists = exists(
            select(1).where(
                UserDepartmentMembership.user_id == User.id,
                UserDepartmentMembership.department_id == department_id,
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
            )
        )
        count_query = count_query.where(dept_exists)
    total_count = (await session.exec(count_query)).first()

    user_ids = [user.id for user in users]
    creator_ids = [user.created_by for user in users if user.created_by]

    org_rows = []
    if user_ids:
        org_rows = (
            await session.exec(
                select(UserOrganizationMembership.user_id, Organization.name)
                .join(Organization, Organization.id == UserOrganizationMembership.org_id)
                .where(
                    UserOrganizationMembership.user_id.in_(user_ids),
                    UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                )
            )
        ).all()

    org_map: dict[UUID, str] = {}
    for uid, org_name in org_rows:
        if uid not in org_map:
            org_map[uid] = org_name

    dept_rows = []
    if user_ids:
        dept_rows = (
            await session.exec(
                select(
                    UserDepartmentMembership.user_id,
                    UserDepartmentMembership.department_id,
                    Department.name,
                )
                .join(Department, Department.id == UserDepartmentMembership.department_id)
                .where(
                    UserDepartmentMembership.user_id.in_(user_ids),
                    UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                )
            )
        ).all()
    dept_map: dict[UUID, UUID] = {}
    dept_name_map: dict[UUID, str] = {}
    for uid, dept_id_value, dept_name in dept_rows:
        if uid not in dept_map:
            dept_map[uid] = dept_id_value
        if uid not in dept_name_map:
            dept_name_map[uid] = dept_name

    creator_map: dict[UUID, str] = {}
    if creator_ids:
        creator_rows = (
            await session.exec(select(User.id, User.username).where(User.id.in_(list(set(creator_ids)))))
        ).all()
        creator_map = {creator_id: creator_username for creator_id, creator_username in creator_rows}

    return UsersResponse(
        total_count=total_count,
        users=[
            UserRead(
                **user.model_dump(exclude={"department_name", "department_id"}),
                organization_name=org_map.get(user.id),
                department_name=dept_name_map.get(user.id) or user.department_name,
                department_id=dept_map.get(user.id),
                created_by_username=creator_map.get(user.created_by) if user.created_by else None,
            )
            for user in users
        ],
    )


@router.get("/{user_id}/department-change-check")
async def get_department_change_check(
    user_id: UUID,
    target_department_id: UUID,
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> dict:
    target_user = await get_user_by_id(session, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    visible_user_ids = await _visible_user_ids_for_admin(session, current_user)
    if user_id not in visible_user_ids:
        raise HTTPException(status_code=403, detail="Permission denied")

    current_role = normalize_role(current_user.role)
    if current_role not in {"root", "super_admin"}:
        raise HTTPException(status_code=403, detail="Only root or super admin can change departments.")

    current_department_id = (
        await session.exec(
            select(UserDepartmentMembership.department_id).where(
                UserDepartmentMembership.user_id == user_id,
                UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
            )
        )
    ).first()

    if not current_department_id or current_department_id == target_department_id:
        return {"can_change": True, "detail": None}

    published_uat_count, published_prod_count = await _published_deployment_counts_for_user(
        session,
        user_id=user_id,
    )
    if published_uat_count or published_prod_count:
        return {
            "can_change": False,
            "detail": "You cannot change the department of a user who has agents published in UAT or PROD. Remove those published agent dependencies first.",
        }

    return {"can_change": True, "detail": None}


async def _move_user_to_department(
    session: DbSession,
    *,
    actor: User,
    target_user: User,
    target_department_id: UUID,
) -> None:
    actor_role = normalize_role(actor.role)
    if actor_role not in {"root", "super_admin"}:
        raise HTTPException(status_code=403, detail="Only root or super admin can change departments.")

    department_query = select(Department).where(
        Department.id == target_department_id,
        Department.status == "active",
    )
    if actor_role == "super_admin":
        org_ids = await _get_admin_org_ids(session, actor)
        if not org_ids:
            raise HTTPException(status_code=403, detail="Permission denied")
        department_query = department_query.where(Department.org_id.in_(list(org_ids)))

    target_department = (await session.exec(department_query)).first()
    if not target_department:
        raise HTTPException(status_code=400, detail="Invalid target department.")

    target_role = normalize_role(target_user.role)
    # Root and super-admin are org-/system-scoped, not department-scoped, so a
    # plain department-change makes no sense for them. department_admin can
    # move — but only when they have no users under them and no published
    # agents (the caller in patch_user enforces those preconditions).
    if target_role in {"root", "super_admin"}:
        raise HTTPException(status_code=400, detail="Department change is not supported for root or super admin users.")

    target_role_entity = await _get_role_entity(session, target_role)

    await _hard_delete_user_assets(
        session,
        target_user=target_user,
    )

    await session.exec(
        update(UserDepartmentMembership)
        .where(
            UserDepartmentMembership.user_id == target_user.id,
            UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
        )
        .values(
            status="inactive",
            updated_at=datetime.now(timezone.utc),
        )
    )

    await session.exec(
        update(UserOrganizationMembership)
        .where(
            UserOrganizationMembership.user_id == target_user.id,
            UserOrganizationMembership.org_id != target_department.org_id,
            UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
        )
        .values(
            status="inactive",
            updated_at=datetime.now(timezone.utc),
        )
    )

    await _ensure_org_membership(
        session,
        user_id=target_user.id,
        org_id=target_department.org_id,
        role_id=target_role_entity.id,
        actor_user_id=actor.id,
    )
    await _ensure_department_membership(
        session,
        user_id=target_user.id,
        org_id=target_department.org_id,
        department_id=target_department.id,
        role_id=target_role_entity.id,
        actor_user_id=actor.id,
    )

    target_department_admin = await session.get(User, target_department.admin_user_id)
    target_user.department_name = target_department.name
    target_user.department_admin = target_department.admin_user_id
    target_user.department_admin_email = (
        target_department_admin.username if target_department_admin else None
    )
    target_user.updated_at = datetime.now(timezone.utc)
    session.add(target_user)


@router.patch("/{user_id}", response_model=UserRead)
async def patch_user(
    user_id: UUID,
    user_update: UserUpdate,
    user: CurrentActiveUser,
    response: Response,
    session: DbSession,
) -> User:
    """Update an existing user's data."""
    update_password = bool(user_update.password)
    non_password_updates = {
        key: value
        for key, value in user_update.model_dump(exclude_unset=True).items()
        if key != "password"
    }

    if user.id != user_id:
        visible_user_ids = await _visible_user_ids_for_admin(session, user)
        if user_id not in visible_user_ids:
            raise HTTPException(status_code=403, detail="Permission denied")
        user_permissions = await get_permissions_for_role(user.role)
        if "view_admin_page" not in user_permissions:
            raise HTTPException(status_code=403, detail="Permission denied")
    if update_password:
        if not user.is_superuser:
            raise HTTPException(status_code=400, detail="You can't change your password here")
        user_update.password = get_password_hash(user_update.password)
        if user_update.role:
            user_update.role = normalize_role(user_update.role)
            assignable_roles = await _assignable_roles_for_creator(session, normalize_role(user.role))
            if user_update.role not in assignable_roles:
                raise HTTPException(status_code=403, detail="Selected role is not assignable by current user.")
            user_update.is_superuser = user_update.role in {"super_admin", "department_admin", "root"}

    if user_db := await get_user_by_id(session, user_id):
        previous_values = {
            "username": user_db.username,
            "email": user_db.email,
            "display_name": user_db.display_name,
            "role": user_db.role,
            "is_active": user_db.is_active,
            "department_name": user_db.department_name,
            "department_admin_email": user_db.department_admin_email,
            "country": user_db.country,
            "organization_name": _strip_or_none(user_update.organization_name),
        }

        # Don't allow demoting a department admin while their department still
        # has active users under them — otherwise the department is left with
        # no admin. Reassign / remove the users first, or promote a new admin.
        if user_update.role is not None:
            requested_role = normalize_role(user_update.role)
            current_role = normalize_role(user_db.role)
            if (
                current_role == "department_admin"
                and requested_role != "department_admin"
                and await _target_has_managed_users(session, user_db)
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This department admin still has users under them. "
                        "Reassign or remove those users (or assign a new "
                        "department admin) before changing this user's role."
                    ),
                )

            # Don't allow promoting a user who's already a member of someone
            # else's department to department_admin. They were created under
            # another admin, and promotion leaves them with the role but no
            # department to admin (control panel and dept-scoped views show
            # nothing). Create a fresh dept admin user instead.
            if (
                requested_role == "department_admin"
                and current_role != "department_admin"
                and await _target_belongs_to_department(session, user_db)
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This user already belongs to a department under another "
                        "department admin and cannot be promoted to department "
                        "admin. Create a new user for this role instead."
                    ),
                )

        requested_department_id = user_update.department_id
        # Only look up the user's current department if a target dept was
        # requested — otherwise the lookup is unused and just adds a DB
        # roundtrip to every non-department edit.
        if requested_department_id:
            current_department_id = (
                await session.exec(
                    select(UserDepartmentMembership.department_id).where(
                        UserDepartmentMembership.user_id == user_db.id,
                        UserDepartmentMembership.status == ACTIVE_DEPT_STATUS,
                    )
                )
            ).first()
            department_change_requested = (
                requested_department_id != current_department_id
            )
        else:
            department_change_requested = False
        if department_change_requested and normalize_role(user.role) in {"root", "super_admin"}:
            # Block the move if the user being moved is a dept admin who
            # still has subordinates — otherwise the old department is left
            # without an admin and the moved admin becomes "rootless" in the
            # new dept while still owning users in the old one.
            if await _target_has_managed_users(session, user_db):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This user still has users under them and cannot be "
                        "moved to a different department. Reassign or remove "
                        "those users first."
                    ),
                )
            published_uat_count, published_prod_count = await _published_deployment_counts_for_user(
                session,
                user_id=user_db.id,
            )
            if published_uat_count or published_prod_count:
                raise HTTPException(
                    status_code=409,
                    detail="You cannot change the department of a user who has agents published in UAT or PROD. Remove those published agent dependencies first.",
                )
            await _move_user_to_department(
                session,
                actor=user,
                target_user=user_db,
                target_department_id=requested_department_id,
            )
            user_update.department_id = None

        # Root promoting/editing a super admin must also ensure org membership mapping.
        if normalize_role(user.role) == "root" and user_update.role == "super_admin":
            organization_name = _strip_or_none(user_update.organization_name)
            organization_description = _strip_or_none(user_update.organization_description)

            if not organization_name:
                existing_super_admin_org = (
                    await session.exec(
                        select(UserOrganizationMembership).where(
                            UserOrganizationMembership.user_id == user_db.id,
                            UserOrganizationMembership.status.in_(list(ACTIVE_ORG_STATUSES)),
                        )
                    )
                ).first()
                if not existing_super_admin_org:
                    raise HTTPException(
                        status_code=400,
                        detail="Organization name is required for super admin.",
                    )
                # Back-fill any missing Langfuse binding for the existing org.
                existing_org = await session.get(
                    Organization, existing_super_admin_org.org_id
                )
                if existing_org:
                    await _ensure_langfuse_org_admin_binding(
                        session,
                        org=existing_org,
                        actor=user,
                    )
            else:
                organization = await _find_organization_by_normalized_name(
                    session,
                    organization_name,
                )
                if not organization:
                    organization = Organization(
                        name=organization_name,
                        description=organization_description,
                        status="active",
                        owner_user_id=user_db.id,
                        created_by=user.id,
                        updated_by=user.id,
                    )
                    session.add(organization)
                    await session.flush()

                super_admin_role = await _get_role_entity(session, "super_admin")
                await _ensure_org_membership(
                    session,
                    user_id=user_db.id,
                    org_id=organization.id,
                    role_id=super_admin_role.id,
                    actor_user_id=user.id,
                )

                root_role = await _get_role_entity(session, "root")
                await _ensure_org_membership(
                    session,
                    user_id=user.id,
                    org_id=organization.id,
                    role_id=root_role.id,
                    actor_user_id=user.id,
                )

                # Mirror the org/admin-project into Langfuse. Idempotent — if the
                # org already has an active binding, the service short-circuits.
                # Without this call, promoting a previously-registered user to
                # super_admin via PATCH leaves Langfuse out of sync with the
                # AgentCore org.
                await _ensure_langfuse_org_admin_binding(
                    session,
                    org=organization,
                    actor=user,
                )

        if not update_password:
            user_update.password = user_db.password
        user_data = user_update.model_dump(exclude_unset=True)
        user_field_changes = any(
            hasattr(user_db, attr) and value is not None
            for attr, value in user_data.items()
        )
        if not user_field_changes:
            await session.commit()
            await session.refresh(user_db)
            if non_password_updates:
                email_sent, email_detail = await send_user_notification_email(
                    settings=get_settings_service().settings,
                    recipient_email=_notification_recipient_for_user(user_db),
                    recipient_name=_display_name_for_user(user_db),
                    subject="Your AgentCore profile was updated",
                    headline="Your AgentCore profile was updated",
                    intro_text="Your account details were updated in AgentCore.",
                    summary_text="No additional field changes were detected, but this action was recorded.",
                    actor_name=_display_name_for_user(user),
                    changed_fields=["Profile information reviewed."],
                    organization_name=_strip_or_none(user_update.organization_name),
                    department_name=user_db.department_name,
                )
                _format_notification_email_status(
                    response,
                    sent=email_sent,
                    detail=email_detail,
                )
            return user_db
        updated_user = await update_user(user_db, user_update, session)
        if non_password_updates:
            email_sent, email_detail = await send_user_notification_email(
                settings=get_settings_service().settings,
                recipient_email=_notification_recipient_for_user(updated_user),
                recipient_name=_display_name_for_user(updated_user),
                subject="Your AgentCore profile was updated",
                headline="Your AgentCore profile was updated",
                intro_text="Your account details were updated in AgentCore.",
                summary_text="Please review the changed fields below.",
                actor_name=_display_name_for_user(user),
                changed_fields=_build_update_user_email_details(
                    previous_values=previous_values,
                    current_user=updated_user,
                    requested_updates=non_password_updates,
                ),
                organization_name=_strip_or_none(user_update.organization_name),
                department_name=updated_user.department_name,
            )
            _format_notification_email_status(
                response,
                sent=email_sent,
                detail=email_detail,
            )
        return updated_user
    raise HTTPException(status_code=404, detail="User not found")


@router.patch("/{user_id}/reset-password", response_model=UserRead)
async def reset_password(
    user_id: UUID,
    user_update: UserUpdate,
    user: CurrentActiveUser,
    session: DbSession,
) -> User:
    """Reset a user's password."""
    if user_id != user.id:
        raise HTTPException(status_code=400, detail="You can't change another user's password")

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if verify_password(user_update.password, user.password):
        raise HTTPException(status_code=400, detail="You can't use your current password")
    user.password = get_password_hash(user_update.password)
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> dict:
    """Delete a user from the database."""
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="You can't delete your own user account")

    user_db = (
        await session.exec(
            select(User).where(
                User.id == user_id,
                User.deleted_at.is_(None),
            )
        )
    ).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        await _can_current_admin_delete_target_user(
            session,
            current_user=current_user,
            target_user=user_db,
        )
        if normalize_role(user_db.role) == "root":
            raise HTTPException(status_code=403, detail="Root users cannot be deleted.")

        delete_blocker = await _get_delete_user_blocker(
            session,
            target_user=user_db,
        )
        if delete_blocker:
            raise HTTPException(
                status_code=409,
                detail=delete_blocker,
            )

        await _hard_delete_user_dependencies(
            session,
            target_user=user_db,
            actor_user_id=current_user.id,
        )

        # Langfuse cleanup: delete projects/orgs that were just archived/suspended in DB.
        try:
            provisioning_service = get_langfuse_provisioning_service()
            if provisioning_service.enabled:
                pass
        except LangfuseProvisioningError:
            pass  # logged inside the service; do not block the delete

        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Could not hard delete user due to remaining database dependencies."
            ),
        ) from e

    return {"detail": "User permanently deleted."}


@router.get("/{user_id}/delete-check")
async def get_delete_user_check(
    user_id: UUID,
    session: DbSession,
    current_user: User = Depends(PermissionChecker(["view_admin_page"])),
) -> dict:
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="You can't delete your own user account")

    user_db = (
        await session.exec(
            select(User).where(
                User.id == user_id,
                User.deleted_at.is_(None),
            )
        )
    ).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")

    await _can_current_admin_delete_target_user(
        session,
        current_user=current_user,
        target_user=user_db,
    )
    if normalize_role(user_db.role) == "root":
        raise HTTPException(status_code=403, detail="Root users cannot be deleted.")

    delete_blocker = await _get_delete_user_blocker(
        session,
        target_user=user_db,
    )

    return {
        "can_delete": delete_blocker is None,
        "detail": delete_blocker,
    }
