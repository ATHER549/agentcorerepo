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
        "activeVersionId": (
            str(row["active_version_id"]) if row.get("active_version_id") else None
        ),
        "activeVersionNumber": (
            int(row["active_version_number"])
            if row.get("active_version_number") is not None
            else None
        ),
        "usedByAgentCount": (
            int(row["used_by_agent_count"])
            if row.get("used_by_agent_count") is not None
            else None
        ),
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


_VERSIONING_OVERLAY_FIELDS = (
    "name",
    "description",
    "category",
    "model_registry_id",
    "runtime_config",
)


async def _list_in_use_prod_guardrails(
    session: DbSession,
    *,
    framework: str | None = None,
) -> list[dict]:
    """Return one synthesized row per (guardrail, version) currently referenced
    by an active prod agent deployment.

    Each row overlays the version's frozen snapshot fields (name, description,
    category, model_registry_id, runtime_config) onto the catalogue identity
    (id, framework, org_id, dept_id, is_custom, visibility, etc.). Includes
    ``active_version_id``, ``active_version_number``, and ``used_by_agent_count``.

    De-duplicates by (guardrail_id, version_id) so the same version used by
    multiple agents appears once.
    """
    from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd
    from agentcore.services.database.models.guardrail_catalogue.model import GuardrailCatalogue
    from agentcore.services.database.models.guardrail_version.model import GuardrailVersion

    active_prods = (
        await session.exec(
            select(AgentDeploymentProd).where(
                AgentDeploymentProd.is_active.is_(True),
                AgentDeploymentProd.is_enabled.is_(True),
            )
        )
    ).all()

    # (guardrail_id, version_id) -> dict with version_number + agent_ids set
    in_use: dict[tuple[str, str], dict[str, Any]] = {}
    # Legacy snapshots without `guardrail_version_refs` — we'll resolve to the
    # currently-active version at the end.
    legacy_gids_per_agent: dict[str, set[str]] = {}

    for dep in active_prods:
        snap = dep.agent_snapshot or {}
        refs = snap.get("guardrail_version_refs") or []

        if refs:
            for ref in refs:
                gid = ref.get("guardrail_id")
                vid = ref.get("guardrail_version_id")
                vnum = ref.get("version_number")
                if not gid or not vid:
                    continue
                key = (str(gid), str(vid))
                entry = in_use.setdefault(key, {
                    "guardrail_id": str(gid),
                    "version_id": str(vid),
                    "version_number": vnum,
                    "agent_ids": set(),
                })
                entry["agent_ids"].add(str(dep.agent_id))
            continue

        # Legacy snapshot: scan nodes for NemoGuardrails references
        try:
            for node in snap.get("nodes", []) or []:
                node_data = node.get("data", {}) or {}
                if node_data.get("type") != "NemoGuardrails":
                    continue
                template = (node_data.get("node", {}) or {}).get("template", {}) or {}
                field = template.get("guardrail_id")
                value = field.get("value") if isinstance(field, dict) else field
                gid: str | None = None
                if isinstance(value, str) and "|" in value:
                    parts = [p.strip() for p in value.split("|")]
                    if len(parts) >= 2:
                        gid = parts[1]
                elif isinstance(value, str) and value.strip():
                    gid = value.strip()
                if gid:
                    legacy_gids_per_agent.setdefault(str(dep.agent_id), set()).add(gid)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to extract legacy guardrail refs from deployment %s",
                getattr(dep, "id", None),
                exc_info=True,
            )

    # Resolve legacy snapshots → currently-active version
    if legacy_gids_per_agent:
        legacy_gid_set = {gid for gids in legacy_gids_per_agent.values() for gid in gids}
        try:
            active_versions = (
                await session.exec(
                    select(GuardrailVersion).where(
                        GuardrailVersion.guardrail_id.in_([UUID(g) for g in legacy_gid_set]),
                        GuardrailVersion.is_active.is_(True),
                    )
                )
            ).all()
            active_by_gid = {str(av.guardrail_id): av for av in active_versions}
            for agent_id, gids in legacy_gids_per_agent.items():
                for gid in gids:
                    av = active_by_gid.get(gid)
                    if av is None:
                        logger.warning(
                            "Legacy prod agent %s references guardrail %s but no "
                            "active version exists; skipping",
                            agent_id, gid,
                        )
                        continue
                    key = (str(av.guardrail_id), str(av.id))
                    entry = in_use.setdefault(key, {
                        "guardrail_id": str(av.guardrail_id),
                        "version_id": str(av.id),
                        "version_number": av.version_number,
                        "agent_ids": set(),
                    })
                    entry["agent_ids"].add(agent_id)
        except Exception:  # noqa: BLE001
            logger.warning("Legacy guardrail resolution failed", exc_info=True)

    if not in_use:
        return []

    # Batched fetch of version snapshots + catalogue identity rows
    version_ids = [UUID(k[1]) for k in in_use]
    catalogue_ids = list({UUID(k[0]) for k in in_use})

    version_rows = (
        await session.exec(select(GuardrailVersion).where(GuardrailVersion.id.in_(version_ids)))
    ).all()
    version_by_id = {str(v.id): v for v in version_rows}

    catalogue_rows = (
        await session.exec(
            select(GuardrailCatalogue).where(GuardrailCatalogue.id.in_(catalogue_ids))
        )
    ).all()
    catalogue_by_id = {str(c.id): c for c in catalogue_rows}

    synthesized: list[dict[str, Any]] = []
    for (gid, vid), info in in_use.items():
        version = version_by_id.get(vid)
        catalogue = catalogue_by_id.get(gid)
        if version is None or catalogue is None:
            continue
        if framework and str(getattr(catalogue, "framework", "")).lower() != framework.lower():
            continue
        snap = version.guardrail_snapshot or {}

        # Start from catalogue identity (org/dept/visibility/etc.) then overlay
        # the version snapshot's mutable identity fields. Stringify UUIDs so
        # the row shape matches the microservice's JSON response — downstream
        # helpers (_can_access_guardrail, _serialize_guardrail) expect strings
        # and explicitly call UUID(row["..."]) on them.
        row: dict[str, Any] = {
            "id": str(catalogue.id),
            "framework": catalogue.framework,
            "provider": catalogue.provider,
            "status": catalogue.status,
            "rules_count": catalogue.rules_count,
            "is_custom": catalogue.is_custom,
            "org_id": str(catalogue.org_id) if catalogue.org_id else None,
            "dept_id": str(catalogue.dept_id) if catalogue.dept_id else None,
            "visibility": catalogue.visibility,
            "public_scope": catalogue.public_scope,
            "shared_user_ids": catalogue.shared_user_ids,
            "public_dept_ids": catalogue.public_dept_ids,
            "created_by": str(catalogue.created_by) if catalogue.created_by else None,
            "created_at": catalogue.created_at,
            "updated_at": catalogue.updated_at,
            "latest_version": catalogue.latest_version,
            "active_version_id": info["version_id"],
            "active_version_number": info.get("version_number") or version.version_number,
            "used_by_agent_count": len(info.get("agent_ids") or []),
        }
        for field in _VERSIONING_OVERLAY_FIELDS:
            if field in snap:
                value = snap[field]
            elif hasattr(catalogue, field):
                value = getattr(catalogue, field)
            else:
                continue
            # `model_registry_id` is consumed downstream via `UUID(row["..."])`
            # so it must be a string. The microservice JSON path already does
            # this; mirror that here when the fallback hands us a UUID object.
            if field == "model_registry_id" and value is not None:
                value = str(value)
            row[field] = value
        synthesized.append(row)

    synthesized.sort(
        key=lambda r: (
            str(r.get("name") or "").strip().lower(),
            -(int(r.get("active_version_number") or 0)),
        )
    )
    return synthesized


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

    if environment == "prod":
        rows = await _list_in_use_prod_guardrails(session, framework=framework)
    else:
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


@router.get("/{guardrail_id}/version-agents")
async def list_version_agent_usage(
    guardrail_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    """Return which production agents are using each version of this guardrail.

    Scans active PROD deployments and builds a ``version_id → agents`` map
    from ``agent_snapshot.guardrail_version_refs``. Also handles legacy
    snapshots that reference guardrails via NemoGuardrails flow nodes without
    explicit version refs.
    """
    await _require_guardrail_permission(current_user, "view_guardrail_page")

    from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd
    from agentcore.services.database.models.guardrail_version.model import GuardrailVersion

    gid_str = str(guardrail_id)

    all_active_prods = (
        await session.exec(
            select(AgentDeploymentProd).where(
                AgentDeploymentProd.is_active.is_(True),
                AgentDeploymentProd.is_enabled.is_(True),
            )
        )
    ).all()

    # Shadow deployments keep ALL versions is_active=True side-by-side.
    # For guardrail version tracking we only care about the *latest*
    # deployment per agent (the one currently serving in PROD), so
    # deduplicate by agent_id, keeping the highest version_number.
    latest_by_agent: dict[str, AgentDeploymentProd] = {}
    for dep in all_active_prods:
        aid = str(dep.agent_id)
        existing = latest_by_agent.get(aid)
        if existing is None or dep.version_number > existing.version_number:
            latest_by_agent[aid] = dep
    active_prods = list(latest_by_agent.values())

    # version_id → list of agent info dicts
    version_agents: dict[str, list[dict[str, Any]]] = {}
    # Legacy deployments without guardrail_version_refs
    legacy_agent_ids: list[str] = []

    logger.info(
        "[VERSION_AGENTS] guardrail_id=%s, active_prods=%d",
        gid_str, len(active_prods),
    )

    for dep in active_prods:
        snap = dep.agent_snapshot or {}
        refs = snap.get("guardrail_version_refs") or []

        logger.info(
            "[VERSION_AGENTS] Checking agent=%s (%s) v%s, has_refs=%s, refs_count=%d",
            dep.agent_name, dep.agent_id, dep.version_number,
            bool(refs), len(refs),
        )

        if refs:
            matched_any = False
            for ref in refs:
                ref_gid = ref.get("guardrail_id")
                vid = ref.get("guardrail_version_id")
                if not ref_gid or not vid:
                    continue
                logger.info(
                    "[VERSION_AGENTS]   ref: guardrail_id=%s, version_id=%s, match=%s",
                    ref_gid, vid, str(ref_gid) == gid_str,
                )
                if str(ref_gid) != gid_str:
                    continue
                matched_any = True
                version_agents.setdefault(str(vid), []).append({
                    "agent_id": str(dep.agent_id),
                    "agent_name": dep.agent_name or str(dep.agent_id),
                    "deployment_version": f"v{dep.version_number}",
                    "deployed_at": (
                        dep.deployed_at.isoformat()
                        if getattr(dep, "deployed_at", None)
                        else None
                    ),
                })
            if not matched_any:
                logger.info(
                    "[VERSION_AGENTS]   No matching refs for guardrail %s in agent %s",
                    gid_str, dep.agent_name,
                )
            continue

        # Legacy: scan NemoGuardrails nodes for matching guardrail_id
        try:
            for node in snap.get("nodes", []) or []:
                node_data = node.get("data", {}) or {}
                if node_data.get("type") != "NemoGuardrails":
                    continue
                template = (node_data.get("node", {}) or {}).get("template", {}) or {}
                field = template.get("guardrail_id")
                value = field.get("value") if isinstance(field, dict) else field
                gid: str | None = None
                if isinstance(value, str) and "|" in value:
                    parts = [p.strip() for p in value.split("|")]
                    if len(parts) >= 2:
                        gid = parts[1]
                elif isinstance(value, str) and value.strip():
                    gid = value.strip()
                if gid and gid == gid_str:
                    legacy_agent_ids.append(str(dep.agent_id))
                    logger.info(
                        "[VERSION_AGENTS]   Legacy match: agent=%s references guardrail=%s",
                        dep.agent_name, gid,
                    )
                    break  # one match per deployment is enough
        except Exception:  # noqa: BLE001
            logger.warning(
                "[VERSION_AGENTS]   Legacy scan failed for agent %s",
                dep.agent_name, exc_info=True,
            )

    logger.info(
        "[VERSION_AGENTS] Refs resolved: %d entries. Legacy agents: %s",
        sum(len(v) for v in version_agents.values()),
        legacy_agent_ids,
    )

    # Resolve legacy agents → guardrail version by deployment timestamp.
    # These deployments predate the guardrail_version_refs feature, so we
    # infer the version by finding the latest guardrail_version whose
    # created_at ≤ the deployment's deployed_at.
    if legacy_agent_ids:
        try:
            all_versions = (
                await session.exec(
                    select(GuardrailVersion)
                    .where(GuardrailVersion.guardrail_id == guardrail_id)
                    .order_by(GuardrailVersion.created_at.asc())
                )
            ).all()

            logger.info(
                "[VERSION_AGENTS] Legacy resolution: %d versions found for guardrail %s",
                len(all_versions), gid_str,
            )

            if all_versions:
                legacy_deps = [
                    dep for dep in active_prods
                    if str(dep.agent_id) in legacy_agent_ids
                ]
                for dep in legacy_deps:
                    dep_time = getattr(dep, "deployed_at", None)
                    # Make both datetimes naive for comparison to avoid
                    # TypeError when mixing tz-aware and tz-naive datetimes
                    dep_time_naive = (
                        dep_time.replace(tzinfo=None) if dep_time else None
                    )
                    matched_version = None
                    if dep_time_naive:
                        for v in all_versions:
                            v_time_naive = (
                                v.created_at.replace(tzinfo=None)
                                if v.created_at else None
                            )
                            if v_time_naive and v_time_naive <= dep_time_naive:
                                matched_version = v
                            else:
                                break
                    # Fallback: if no version predates the deployment,
                    # use the earliest version available
                    if matched_version is None and all_versions:
                        matched_version = all_versions[0]

                    logger.info(
                        "[VERSION_AGENTS]   Legacy agent=%s deployed_at=%s → matched version=%s",
                        dep.agent_name,
                        dep_time,
                        f"v{matched_version.version_number}" if matched_version else "None",
                    )

                    if matched_version:
                        vid = str(matched_version.id)
                        version_agents.setdefault(vid, []).append({
                            "agent_id": str(dep.agent_id),
                            "agent_name": dep.agent_name or str(dep.agent_id),
                            "deployment_version": f"v{dep.version_number}",
                            "deployed_at": (
                                dep_time.isoformat() if dep_time else None
                            ),
                        })
        except Exception:  # noqa: BLE001
            logger.warning(
                "Legacy guardrail resolution for version-agents failed for %s",
                guardrail_id,
                exc_info=True,
            )

    return {
        "guardrail_id": gid_str,
        "version_agents": version_agents,
    }
