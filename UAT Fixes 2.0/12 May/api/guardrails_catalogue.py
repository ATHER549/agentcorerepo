from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.auth.permissions import get_permissions_for_role, normalize_role
from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.model_registry.model import ModelRegistry
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.user_department_membership.model import UserDepartmentMembership
from agentcore.services.database.models.user_organization_membership.model import UserOrganizationMembership
from agentcore.services.guardrail_service_client import (
    create_guardrail_via_service,
    delete_guardrail_via_service,
    fetch_guardrails_async,
    get_guardrail_via_service,
    get_guardrail_version_via_service,
    get_guardrail_versions_via_service,
    invalidate_guardrail_cache_via_service,
    update_guardrail_via_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/guardrails-catalogue", tags=["Guardrails Catalogue"])


class GuardrailPayload(BaseModel):
    name: str
    description: str | None = None
    framework: str | None = None
    provider: str | None = None
    modelRegistryId: UUID | None = None
    category: str
    status: str = "active"
    rulesCount: int | None = None
    isCustom: bool = False
    runtimeConfig: dict[str, Any] | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str = "private"  # private | public
    public_scope: str | None = None  # organization | department
    public_dept_ids: list[UUID] | None = None


class GuardrailUpdatePayload(BaseModel):
    name: str | None = None
    description: str | None = None
    framework: str | None = None
    provider: str | None = None
    modelRegistryId: UUID | None = None
    category: str | None = None
    status: str | None = None
    rulesCount: int | None = None
    isCustom: bool | None = None
    runtimeConfig: dict[str, Any] | None = None
    org_id: UUID | None = None
    dept_id: UUID | None = None
    visibility: str | None = None
    public_scope: str | None = None
    public_dept_ids: list[UUID] | None = None


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    return str(getattr(current_user, "role", "")).lower() == "root"


async def _require_guardrail_permission(current_user: CurrentActiveUser, permission: str) -> None:
    user_permissions = await get_permissions_for_role(str(current_user.role))
    if permission not in user_permissions:
        raise HTTPException(status_code=403, detail="Missing required permissions")


def _normalize_visibility(value: str | None) -> str:
    normalized = (value or "private").strip().lower()
    if normalized not in {"private", "public"}:
        raise HTTPException(status_code=400, detail=f"Unsupported visibility '{value}'")
    return normalized


def _normalize_public_scope(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"organization", "department"}:
        raise HTTPException(status_code=400, detail=f"Unsupported public_scope '{value}'")
    return normalized


def _normalize_guardrail_framework(value: str | None) -> str:
    normalized = (value or "nemo").strip().lower()
    if normalized not in {"nemo", "arize"}:
        raise HTTPException(status_code=400, detail=f"Unsupported framework '{value}'")
    return normalized


def _string_ids(values: list[UUID] | None) -> list[str]:
    return [str(v) for v in (values or [])]


def _field_supplied(payload: BaseModel, field_name: str) -> bool:
    fields_set = getattr(payload, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(payload, "__fields_set__", set())
    return field_name in fields_set


def _first_membership_scope(
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> tuple[UUID | None, UUID | None]:
    if dept_pairs:
        current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
        return current_org_id, current_dept_id
    if org_ids:
        return sorted(org_ids, key=str)[0], None
    return None, None


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


async def _validate_scope_refs(session: DbSession, payload: GuardrailPayload | GuardrailUpdatePayload) -> None:
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


async def _enforce_creation_scope(
    session: DbSession,
    current_user: CurrentActiveUser,
    payload: GuardrailPayload | GuardrailUpdatePayload,
) -> tuple[str, str | None, list[str]]:
    user_role = normalize_role(str(current_user.role))
    visibility = _normalize_visibility(getattr(payload, "visibility", None))
    public_scope = _normalize_public_scope(getattr(payload, "public_scope", None))
    public_dept_ids = _string_ids(getattr(payload, "public_dept_ids", None))
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)

    if user_role not in {"root", "super_admin", "department_admin", "developer", "business_user"}:
        raise HTTPException(status_code=403, detail="Your role is not allowed to create guardrails")

    if visibility == "private":
        payload.public_scope = None
        payload.public_dept_ids = None
        if user_role == "root":
            payload.org_id = None
            payload.dept_id = None
        elif user_role == "super_admin":
            current_org_id, _ = _first_membership_scope(org_ids, dept_pairs)
            if not current_org_id:
                raise HTTPException(status_code=403, detail="No active organization scope found")
            payload.org_id = current_org_id
            payload.dept_id = None
        elif user_role in {"department_admin", "developer", "business_user"}:
            current_org_id, current_dept_id = _first_membership_scope(org_ids, dept_pairs)
            if not current_org_id or not current_dept_id:
                raise HTTPException(status_code=403, detail="No active department scope found")
            payload.org_id = current_org_id
            payload.dept_id = current_dept_id
        else:
            payload.org_id = None
            payload.dept_id = None
    else:
        if public_scope is None:
            raise HTTPException(status_code=400, detail="public_scope is required when visibility is public")
        if public_scope == "organization":
            if not payload.org_id:
                raise HTTPException(status_code=400, detail="org_id is required for public organization visibility")
            if user_role != "root" and payload.org_id not in org_ids:
                raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
            payload.dept_id = None
            payload.public_dept_ids = None
            public_dept_ids = []
        else:
            if user_role in {"super_admin", "root"}:
                if not payload.org_id:
                    raise HTTPException(status_code=400, detail="org_id is required for department visibility")
                if user_role != "root" and payload.org_id not in org_ids:
                    raise HTTPException(status_code=403, detail="org_id must belong to your organization scope")
                if not public_dept_ids and payload.dept_id:
                    public_dept_ids = [str(payload.dept_id)]
                if not public_dept_ids:
                    raise HTTPException(status_code=400, detail="Select at least one department")
                await _validate_departments_exist_for_org(session, payload.org_id, [UUID(v) for v in public_dept_ids])
                payload.dept_id = UUID(public_dept_ids[0]) if len(public_dept_ids) == 1 else None
            else:
                if not dept_pairs:
                    raise HTTPException(status_code=403, detail="No active department scope found")
                current_org_id, current_dept_id = sorted(dept_pairs, key=lambda x: (str(x[0]), str(x[1])))[0]
                payload.org_id = current_org_id
                payload.dept_id = current_dept_id
                public_dept_ids = [str(current_dept_id)]
    await _validate_scope_refs(session, payload)
    return visibility, public_scope, public_dept_ids


def _can_access_guardrail(
    row: dict[str, Any],
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    row_org_id = UUID(row["org_id"]) if row.get("org_id") else None
    row_dept_id = UUID(row["dept_id"]) if row.get("dept_id") else None
    row_created_by = row.get("created_by")
    row_visibility = (row.get("visibility") or "private").strip().lower()
    row_public_scope = row.get("public_scope")
    row_public_dept_ids = row.get("public_dept_ids") or []

    if _is_root_user(current_user):
        return (
            str(row_created_by) == str(current_user.id)
            and row_org_id is None
            and row_dept_id is None
        )

    role = normalize_role(str(current_user.role))
    if role == "super_admin" and row_org_id and row_org_id in org_ids:
        return True

    user_id = str(current_user.id)
    dept_id_set = {str(dept_id) for _, dept_id in dept_pairs}

    if row_visibility == "private":
        if role == "department_admin":
            return bool(row_dept_id and str(row_dept_id) in dept_id_set)
        return str(row_created_by) == user_id
    if row_public_scope == "organization":
        return bool(row_org_id and row_org_id in org_ids)
    if row_public_scope == "department":
        dept_candidates = set(row_public_dept_ids)
        if row_dept_id:
            dept_candidates.add(str(row_dept_id))
        return bool(dept_candidates.intersection(dept_id_set))
    return False


def _guardrail_dept_candidates(row: dict[str, Any]) -> set[str]:
    dept_candidates = set(row.get("public_dept_ids") or [])
    if row.get("dept_id"):
        dept_candidates.add(str(row.get("dept_id")))
    return dept_candidates


def _is_multi_dept_guardrail(row: dict[str, Any]) -> bool:
    return (
        (row.get("visibility") or "private").strip().lower() == "public"
        and row.get("public_scope") == "department"
        and len(_guardrail_dept_candidates(row)) > 1
    )


def _can_edit_guardrail(
    row: dict[str, Any],
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return (
            str(row.get("created_by")) == str(current_user.id)
            and row.get("org_id") is None
            and row.get("dept_id") is None
        )

    role = normalize_role(str(current_user.role))
    row_org_id = UUID(row["org_id"]) if row.get("org_id") else None
    row_visibility = (row.get("visibility") or "private").strip().lower()
    row_created_by = str(row.get("created_by"))

    if role == "super_admin":
        if row_visibility == "private" and row_org_id is None and row.get("dept_id") is None:
            return row_created_by == str(current_user.id)
        return bool(row_org_id and row_org_id in org_ids)

    if role == "department_admin":
        if _is_multi_dept_guardrail(row):
            return False
        if (row.get("visibility") or "private").strip().lower() == "public" and row.get("public_scope") == "organization":
            return False
        dept_id_set = {str(dept_id) for _, dept_id in dept_pairs}
        dept_candidates = _guardrail_dept_candidates(row)
        if (row.get("visibility") or "private").strip().lower() == "private":
            return bool(dept_candidates.intersection(dept_id_set))
        if row.get("public_scope") == "department":
            return bool(dept_candidates.intersection(dept_id_set))
        return False

    if role in {"developer", "business_user"}:
        return (row.get("visibility") or "private").strip().lower() == "private" and str(row.get("created_by")) == str(current_user.id)

    return False


def _can_delete_guardrail(
    row: dict[str, Any],
    current_user: CurrentActiveUser,
    org_ids: set[UUID],
    dept_pairs: list[tuple[UUID, UUID]],
) -> bool:
    if _is_root_user(current_user):
        return (
            str(row.get("created_by")) == str(current_user.id)
            and row.get("org_id") is None
            and row.get("dept_id") is None
        )

    role = normalize_role(str(current_user.role))
    user_id = str(current_user.id)
    row_org_id = UUID(row["org_id"]) if row.get("org_id") else None
    row_visibility = (row.get("visibility") or "private").strip().lower()

    if role == "super_admin":
        if row_visibility == "private" and row_org_id is None and row.get("dept_id") is None:
            return str(row.get("created_by")) == user_id
        return bool(row_org_id and row_org_id in org_ids)

    if role == "department_admin":
        if _is_multi_dept_guardrail(row):
            return False
        if (row.get("visibility") or "private").strip().lower() == "public" and row.get("public_scope") == "organization":
            return False
        dept_id_set = {str(dept_id) for _, dept_id in dept_pairs}
        dept_candidates = _guardrail_dept_candidates(row)
        if (row.get("visibility") or "private").strip().lower() == "private":
            return bool(dept_candidates.intersection(dept_id_set))
        if row.get("public_scope") == "department":
            return bool(dept_candidates.intersection(dept_id_set))
        return False

    if role in {"developer", "business_user"}:
        return (row.get("visibility") or "private").strip().lower() == "private" and str(row.get("created_by")) == user_id

    return False


def _validate_runtime_config_shape(payload: GuardrailPayload | GuardrailUpdatePayload) -> None:
    runtime_config = payload.runtimeConfig
    if runtime_config is None:
        return
    if not isinstance(runtime_config, dict):
        raise HTTPException(status_code=400, detail="runtimeConfig must be a JSON object")

    for key in (
        "config_yml",
        "configYml",
        "config.yml",
        "rails_co",
        "railsCo",
        "rails.co",
        "rails_yml",
        "railsYml",
        "rails.yml",
        "prompts_yml",
    ):
        if key not in runtime_config:
            continue
        value = runtime_config.get(key)
        if value is not None and not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"runtimeConfig.{key} must be a string")

    files = runtime_config.get("files")
    if files is None:
        return
    if not isinstance(files, dict):
        raise HTTPException(status_code=400, detail="runtimeConfig.files must be an object")
    invalid_entry = next(
        ((k, v) for k, v in files.items() if not isinstance(k, str) or not isinstance(v, str)),
        None,
    )
    if invalid_entry:
        raise HTTPException(status_code=400, detail="runtimeConfig.files must map string path to string content")


def _extract_runtime_string(runtime_config: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = runtime_config.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            normalized = value.strip()
            if normalized and normalized not in {".", "..."}:
                return normalized
    return None


def _normalize_runtime_config_payload(runtime_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(runtime_config, dict):
        return None

    config_yml = _extract_runtime_string(runtime_config, ("config_yml", "configYml", "config.yml"))
    rails_co = _extract_runtime_string(
        runtime_config,
        ("rails_co", "railsCo", "rails.co", "rails_yml", "railsYml", "rails.yml"),
    )
    prompts_yml = _extract_runtime_string(runtime_config, ("prompts_yml", "promptsYml", "prompts.yml"))
    files = runtime_config.get("files")

    normalized_files: dict[str, str] | None = None
    if isinstance(files, dict):
        parsed_files = {k.strip(): v for k, v in files.items() if isinstance(k, str) and isinstance(v, str) and k.strip()}
        if parsed_files:
            normalized_files = parsed_files

    normalized: dict[str, Any] = {}
    if config_yml:
        normalized["config_yml"] = config_yml
    if rails_co:
        normalized["rails_co"] = rails_co
    if prompts_yml:
        normalized["prompts_yml"] = prompts_yml
    if normalized_files:
        normalized["files"] = normalized_files

    return normalized or None


def _is_nemo_runtime_config_ready(
    runtime_config: dict[str, Any] | None,
    model_registry_id: UUID | None,
) -> bool:
    """Check locally (without calling the microservice) whether a runtime config is complete."""
    if not model_registry_id:
        return False
    if not isinstance(runtime_config, dict):
        return False
    for key in ("config_yml", "configYml", "config.yml"):
        value = runtime_config.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in {".", "..."}:
            return True
    return False


def _hydrate_guardrail_update_payload(payload: GuardrailUpdatePayload, row: dict[str, Any]) -> None:
    if not _field_supplied(payload, "name"):
        payload.name = row.get("name")
    if not _field_supplied(payload, "description"):
        payload.description = row.get("description")
    if not _field_supplied(payload, "framework"):
        payload.framework = row.get("framework")
    if not _field_supplied(payload, "modelRegistryId"):
        payload.modelRegistryId = UUID(row["model_registry_id"]) if row.get("model_registry_id") else None
    if not _field_supplied(payload, "category"):
        payload.category = row.get("category")
    if not _field_supplied(payload, "status"):
        payload.status = row.get("status")
    if not _field_supplied(payload, "rulesCount"):
        payload.rulesCount = row.get("rules_count")
    if not _field_supplied(payload, "isCustom"):
        payload.isCustom = row.get("is_custom")
    if not _field_supplied(payload, "runtimeConfig"):
        payload.runtimeConfig = row.get("runtime_config")
    if not _field_supplied(payload, "org_id"):
        payload.org_id = UUID(row["org_id"]) if row.get("org_id") else None
    if not _field_supplied(payload, "visibility"):
        payload.visibility = row.get("visibility")
    if not _field_supplied(payload, "public_scope"):
        payload.public_scope = row.get("public_scope")
    if not _field_supplied(payload, "public_dept_ids"):
        payload.public_dept_ids = [UUID(v) for v in (row.get("public_dept_ids") or [])]
    if not _field_supplied(payload, "dept_id") and payload.public_scope != "organization":
        payload.dept_id = UUID(row["dept_id"]) if row.get("dept_id") else None


def _serialize_guardrail(
    row: dict[str, Any],
    model_row: ModelRegistry | None = None,
    created_by_lookup: dict[str, dict[str, str | None]] | None = None,
) -> dict:
    model_provider = row.get("provider")
    model_name: str | None = None
    model_display_name: str | None = None
    if model_row:
        model_provider = model_row.provider or row.get("provider")
        model_name = model_row.model_name
        model_display_name = model_row.display_name

    model_registry_id = row.get("model_registry_id")
    runtime_config = row.get("runtime_config")

    serialized = {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description") or "",
        "framework": row.get("framework") or "nemo",
        "provider": model_provider,
        "modelRegistryId": str(model_registry_id) if model_registry_id else None,
        "modelName": model_name,
        "modelDisplayName": model_display_name,
        "category": row.get("category"),
        "status": row.get("status"),
        "rulesCount": int(row.get("rules_count") or 0),
        "isCustom": bool(row.get("is_custom")),
        "runtimeConfig": runtime_config,
        "runtimeReady": _is_nemo_runtime_config_ready(
            runtime_config,
            UUID(model_registry_id) if model_registry_id else None,
        ),
        "org_id": row.get("org_id"),
        "dept_id": row.get("dept_id"),
        "visibility": row.get("visibility"),
        "public_scope": row.get("public_scope"),
        "public_dept_ids": row.get("public_dept_ids") or [],
        "created_by": (created_by_lookup or {}).get(str(row.get("created_by")), {}).get("display") if row.get("created_by") else None,
        "created_by_email": (created_by_lookup or {}).get(str(row.get("created_by")), {}).get("email") if row.get("created_by") else None,
        "created_by_id": str(row["created_by"]) if row.get("created_by") else None,
        # Versioning
        "latestVersion": int(row.get("latest_version") or 0),
    }
    return serialized


def _creator_display_name(display_name: str | None, email: str | None, username: str | None) -> str | None:
    name = str(display_name or "").strip()
    if name:
        return name
    normalized_email = str(email or "").strip()
    if normalized_email:
        return normalized_email.split("@", 1)[0] if "@" in normalized_email else normalized_email
    normalized_username = str(username or "").strip()
    if normalized_username:
        return normalized_username.split("@", 1)[0] if "@" in normalized_username else normalized_username
    return None


def _creator_email(email: str | None, username: str | None) -> str | None:
    normalized_email = str(email or "").strip()
    if normalized_email:
        return normalized_email
    normalized_username = str(username or "").strip()
    if normalized_username and "@" in normalized_username:
        return normalized_username
    return None


async def _resolve_guardrail_model_registry(
    session: DbSession,
    model_registry_id: UUID | None,
) -> ModelRegistry:
    if model_registry_id is None:
        raise HTTPException(status_code=400, detail="modelRegistryId is required")

    model_row = await session.get(ModelRegistry, model_registry_id)
    if not model_row:
        raise HTTPException(status_code=400, detail="Invalid modelRegistryId")
    if not bool(model_row.is_active):
        raise HTTPException(status_code=400, detail="Selected model registry entry is inactive")
    return model_row


@router.get("")
@router.get("/")
async def list_guardrails_catalogue(
    current_user: CurrentActiveUser,
    session: DbSession,
    framework: str | None = None,
    environment: str | None = None,
) -> list[dict]:
    await _require_guardrail_permission(current_user, "view_guardrail_page")

    if environment not in (None, "uat", "prod"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported environment: {environment}",
        )

    rows = await fetch_guardrails_async(framework=framework, environment=environment)

    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    rows = [row for row in rows if _can_access_guardrail(row, current_user, org_ids, dept_pairs)]
    rows.sort(key=lambda row: str(row.get("name") or "").strip().lower())

    model_ids = {UUID(row["model_registry_id"]) for row in rows if row.get("model_registry_id")}
    model_by_id: dict[str, ModelRegistry] = {}
    if model_ids:
        from sqlmodel import select as sql_select
        model_rows = (
            await session.exec(sql_select(ModelRegistry).where(ModelRegistry.id.in_(list(model_ids))))
        ).all()
        model_by_id = {str(model.id): model for model in model_rows}

    creator_ids = [UUID(row["created_by"]) for row in rows if row.get("created_by")]
    created_by_lookup: dict[str, dict[str, str | None]] = {}
    if creator_ids:
        creator_rows = (
            await session.exec(
                select(User.id, User.display_name, User.email, User.username).where(User.id.in_(creator_ids))
            )
        ).all()
        created_by_lookup = {
            str(row[0]): {
                "display": _creator_display_name(row[1], row[2], row[3]) or str(row[0]),
                "email": _creator_email(row[2], row[3]),
            }
            for row in creator_rows
        }

    return [
        _serialize_guardrail(
            row,
            model_by_id.get(str(row.get("model_registry_id"))),
            created_by_lookup,
        )
        for row in rows
    ]


@router.get("/visibility-options")
async def get_guardrail_visibility_options(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_guardrail_permission(current_user, "view_guardrail_page")
    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    role = normalize_role(str(current_user.role))

    organizations = []
    if role == "root":
        org_rows = (await session.exec(select(Organization.id, Organization.name).where(Organization.status == "active"))).all()
        organizations = [{"id": str(r[0]), "name": r[1]} for r in org_rows]
    elif org_ids:
        org_rows = (
            await session.exec(select(Organization.id, Organization.name).where(Organization.id.in_(list(org_ids)), Organization.status == "active"))
        ).all()
        organizations = [{"id": str(r[0]), "name": r[1]} for r in org_rows]

    dept_ids = {dept_id for _, dept_id in dept_pairs}
    departments = []
    if role == "root":
        dept_rows = (await session.exec(select(Department.id, Department.name, Department.org_id).where(Department.status == "active"))).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]
    elif role == "super_admin" and org_ids:
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id).where(Department.org_id.in_(list(org_ids)), Department.status == "active")
            )
        ).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]
    elif dept_ids:
        dept_rows = (
            await session.exec(
                select(Department.id, Department.name, Department.org_id).where(Department.id.in_(list(dept_ids)), Department.status == "active")
            )
        ).all()
        departments = [{"id": str(r[0]), "name": r[1], "org_id": str(r[2])} for r in dept_rows]

    return {
        "organizations": organizations,
        "departments": departments,
        "role": role,
    }


@router.post("")
@router.post("/")
async def create_guardrail_catalogue(
    payload: GuardrailPayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_guardrail_permission(current_user, "view_guardrail_page")
    await _require_guardrail_permission(current_user, "add_guardrails")

    visibility, public_scope, public_dept_ids = await _enforce_creation_scope(
        session, current_user, payload
    )
    framework = _normalize_guardrail_framework(payload.framework)
    model_row = await _resolve_guardrail_model_registry(session, payload.modelRegistryId)
    _validate_runtime_config_shape(payload)
    normalized_runtime_config = _normalize_runtime_config_payload(payload.runtimeConfig)
    if payload.status == "active" and not normalized_runtime_config:
        raise HTTPException(
            status_code=400,
            detail="Active guardrails require runtimeConfig with at least config_yml.",
        )
    if payload.status == "active" and not _is_nemo_runtime_config_ready(normalized_runtime_config, model_row.id):
        raise HTTPException(
            status_code=400,
            detail="runtimeConfig is incomplete. Provide a valid config_yml (rails_co is optional).",
        )

    now = datetime.now(timezone.utc)
    service_payload = {
        "name": payload.name,
        "description": payload.description,
        "framework": framework,
        "provider": model_row.provider,
        "model_registry_id": str(model_row.id),
        "category": payload.category,
        "status": payload.status,
        "rules_count": payload.rulesCount or 0,
        "is_custom": payload.isCustom,
        "runtime_config": normalized_runtime_config,
        "org_id": str(payload.org_id) if payload.org_id else None,
        "dept_id": str(payload.dept_id) if payload.dept_id else None,
        "visibility": visibility,
        "public_scope": public_scope,
        "public_dept_ids": public_dept_ids,
        "shared_user_ids": [],
        "created_by": str(current_user.id),
        "updated_by": str(current_user.id),
        "published_by": str(current_user.id) if payload.status == "active" else None,
        "published_at": now.isoformat() if payload.status == "active" else None,
    }

    logger.info(
        f"Creating guardrail '{payload.name}' via service: model_registry_id={model_row.id}"
    )
    try:
        row = await create_guardrail_via_service(service_payload)
    except Exception as exc:
        logger.exception(f"Guardrail creation via service failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Guardrails service error: {exc}") from exc

    await invalidate_guardrail_cache_via_service(row["id"])
    return _serialize_guardrail(row, model_row)


@router.patch("/{guardrail_id}")
async def update_guardrail_catalogue(
    guardrail_id: UUID,
    payload: GuardrailUpdatePayload,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_guardrail_permission(current_user, "view_guardrail_page")
    await _require_guardrail_permission(current_user, "add_guardrails")

    try:
        row = await get_guardrail_via_service(guardrail_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Guardrail not found") from exc

    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_edit_guardrail(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Not authorized to edit this guardrail")

    _hydrate_guardrail_update_payload(payload, row)
    framework = _normalize_guardrail_framework(payload.framework)

    visibility, public_scope, public_dept_ids = await _enforce_creation_scope(
        session, current_user, payload
    )
    model_row = await _resolve_guardrail_model_registry(session, payload.modelRegistryId)
    _validate_runtime_config_shape(payload)
    normalized_runtime_config = _normalize_runtime_config_payload(payload.runtimeConfig)
    if payload.status == "active" and not normalized_runtime_config:
        raise HTTPException(
            status_code=400,
            detail="Active guardrails require runtimeConfig with at least config_yml.",
        )
    if payload.status == "active" and not _is_nemo_runtime_config_ready(normalized_runtime_config, model_row.id):
        raise HTTPException(
            status_code=400,
            detail="runtimeConfig is incomplete. Provide a valid config_yml (rails_co is optional).",
        )

    now = datetime.now(timezone.utc)
    service_payload = {
        "name": payload.name,
        "description": payload.description,
        "framework": framework,
        "provider": model_row.provider,
        "model_registry_id": str(model_row.id),
        "category": payload.category,
        "status": payload.status,
        "rules_count": payload.rulesCount,
        "is_custom": payload.isCustom,
        "runtime_config": normalized_runtime_config,
        "org_id": str(payload.org_id) if payload.org_id else None,
        "dept_id": str(payload.dept_id) if payload.dept_id else None,
        "visibility": visibility,
        "public_scope": public_scope,
        "public_dept_ids": public_dept_ids,
        "shared_user_ids": [],
        "created_by": str(current_user.id) if visibility == "private" else row.get("created_by"),
        "updated_by": str(current_user.id),
        "published_by": str(current_user.id) if payload.status == "active" else row.get("published_by"),
        "published_at": now.isoformat() if payload.status == "active" else row.get("published_at"),
    }

    logger.info(
        f"Updating guardrail '{row.get('name')}' (id={guardrail_id}) via service: "
        f"new model_registry_id={model_row.id}"
    )
    try:
        updated_row = await update_guardrail_via_service(guardrail_id, service_payload)
    except Exception as exc:
        logger.exception(f"Guardrail update via service failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Guardrails service error: {exc}") from exc

    await invalidate_guardrail_cache_via_service(guardrail_id)
    return _serialize_guardrail(updated_row, model_row)


@router.delete("/{guardrail_id}")
async def delete_guardrail_catalogue(
    guardrail_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    await _require_guardrail_permission(current_user, "view_guardrail_page")
    await _require_guardrail_permission(current_user, "retire_guardrails")

    try:
        row = await get_guardrail_via_service(guardrail_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Guardrail not found") from exc

    org_ids, dept_pairs = await _get_scope_memberships(session, current_user.id)
    if not _can_delete_guardrail(row, current_user, org_ids, dept_pairs):
        raise HTTPException(status_code=403, detail="Not authorized to delete this guardrail")

    # ── Guard: prevent deletion of guardrails used in production ──
    try:
        from agentcore.services.guardrail_service_client import get_guardrail_sync_status_via_service

        sync_status = await get_guardrail_sync_status_via_service(guardrail_id)
        if sync_status.get("has_active_version", False):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot delete this guardrail — it has an active production "
                    f"version (v{sync_status.get('version_number', '?')}). "
                    "Deactivate the version or remove the production agents first."
                ),
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        # Sync-status check is best-effort; the microservice also guards deletion
        logger.warning(
            "Could not check guardrail version status before deletion (non-fatal): guardrail_id=%s",
            guardrail_id,
            exc_info=True,
        )

    try:
        await delete_guardrail_via_service(guardrail_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            raise HTTPException(status_code=409, detail=exc.response.json().get("detail", str(exc))) from exc
        logger.exception(f"Guardrail deletion via service failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Guardrails service error: {exc}") from exc
    except Exception as exc:
        logger.exception(f"Guardrail deletion via service failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Guardrails service error: {exc}") from exc

    await invalidate_guardrail_cache_via_service(guardrail_id)
    return {"message": "Guardrail deleted successfully"}


# ---------------------------------------------------------------------------
# Guardrail version endpoints
# ---------------------------------------------------------------------------


@router.get("/{guardrail_id}/versions")
async def list_guardrail_versions(
    guardrail_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """List all versions for a guardrail, ordered by version number descending."""
    await _require_guardrail_permission(current_user, "view_guardrail_page")

    try:
        result = await get_guardrail_versions_via_service(guardrail_id)
    except Exception as exc:
        logger.exception(f"Failed to fetch guardrail versions: {exc}")
        raise HTTPException(status_code=502, detail=f"Guardrails service error: {exc}") from exc

    return result


@router.get("/{guardrail_id}/versions/{version_id}")
async def get_guardrail_version(
    guardrail_id: UUID,
    version_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Get a specific guardrail version by ID, including its frozen snapshot."""
    await _require_guardrail_permission(current_user, "view_guardrail_page")

    try:
        result = await get_guardrail_version_via_service(guardrail_id, version_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Guardrail version not found") from exc
        raise HTTPException(status_code=502, detail=f"Guardrails service error: {exc}") from exc
    except Exception as exc:
        logger.exception(f"Failed to fetch guardrail version: {exc}")
        raise HTTPException(status_code=502, detail=f"Guardrails service error: {exc}") from exc

    return result
