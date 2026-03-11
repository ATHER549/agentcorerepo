from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.deps import get_cache_service, get_settings_service
from agentcore.services.database.models.timeout_settings.model import TimeoutSettings

router = APIRouter(prefix="/timeout-settings", tags=["Timeout Settings"])


class TimeoutSettingPayload(BaseModel):
    id: str
    label: str
    value: str
    unit: str
    units: list[str]
    description: str
    type: str
    checked: bool | None = None


DEFAULT_TIMEOUT_SETTINGS: list[dict] = [
    {
        "id": "session_timeout",
        "label": "Session Timeout",
        "value": "30",
        "unit": "min",
        "units": ["min", "hr"],
        "description": "Session expiration duration",
        "type": "input",
        "checked": None,
    },
    {
        "id": "cookie_timeout",
        "label": "Cookie Timeout",
        "value": "7",
        "unit": "days",
        "units": ["days", "hr"],
        "description": "Cookie lifetime",
        "type": "input",
        "checked": None,
    },
    {
        "id": "persistent_cookie",
        "label": "Persistent Cookie",
        "value": "",
        "unit": "",
        "units": [],
        "description": "Keep user logged in",
        "type": "switch",
        "checked": True,
    },
    {
        "id": "redis_ttl",
        "label": "Redis TTL",
        "value": "3600",
        "unit": "sec",
        "units": ["sec", "min"],
        "description": "Default Redis object expiry",
        "type": "input",
        "checked": None,
    },
]
DEFAULT_ORDER = {item["id"]: idx for idx, item in enumerate(DEFAULT_TIMEOUT_SETTINGS)}


def _is_root_user(current_user: CurrentActiveUser) -> bool:
    return str(getattr(current_user, "role", "")).lower() == "root"


def _parse_redis_ttl_seconds(value: str | None, unit: str | None) -> int | None:
    if value is None:
        return None
    try:
        numeric_value = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    if numeric_value <= 0:
        return None

    normalized_unit = (unit or "sec").strip().lower()
    if normalized_unit in {"sec", "second", "seconds"}:
        return numeric_value
    if normalized_unit in {"min", "minute", "minutes"}:
        return numeric_value * 60
    return None


def _apply_runtime_redis_ttl(redis_ttl_seconds: int) -> None:
    settings_service = get_settings_service()
    settings_service.settings.redis_cache_expire = redis_ttl_seconds
    settings_service.settings.cache_expire = redis_ttl_seconds

    cache_service = get_cache_service()
    if hasattr(cache_service, "expiration_time"):
        setattr(cache_service, "expiration_time", redis_ttl_seconds)

    # Keep role-permission cache writes aligned with new TTL, if initialized.
    try:
        from agentcore.services.auth import permissions as permissions_module

        if getattr(permissions_module, "permission_cache", None) is not None:
            permissions_module.permission_cache.ttl = redis_ttl_seconds
    except Exception:
        # Optional runtime sync; failures here should not block config updates.
        pass


async def _ensure_defaults(session: DbSession, current_user: CurrentActiveUser) -> None:
    rows = (await session.exec(select(TimeoutSettings.id).limit(1))).first()
    if rows is not None:
        return

    now = datetime.now(timezone.utc)
    for item in DEFAULT_TIMEOUT_SETTINGS:
        session.add(
            TimeoutSettings(
                setting_key=item["id"],
                label=item["label"],
                value=item["value"],
                unit=item["unit"],
                units=item["units"],
                description=item["description"],
                setting_type=item["type"],
                checked=item["checked"],
                created_by=current_user.id,
                updated_by=current_user.id,
                created_at=now,
                updated_at=now,
            )
        )
    await session.commit()


@router.get("")
@router.get("/")
async def get_timeout_settings(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict]:
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    await _ensure_defaults(session, current_user)
    rows = (
        await session.exec(
            select(TimeoutSettings)
        )
    ).all()
    rows = sorted(rows, key=lambda row: DEFAULT_ORDER.get(row.setting_key, 999))

    return [
        {
            "id": row.setting_key,
            "label": row.label,
            "value": row.value or "",
            "unit": row.unit or "",
            "units": row.units or [],
            "description": row.description or "",
            "type": row.setting_type,
            "checked": row.checked,
        }
        for row in rows
    ]


@router.put("")
@router.put("/")
async def update_timeout_settings(
    payload: list[TimeoutSettingPayload],
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict:
    if not _is_root_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Root admin only.")

    now = datetime.now(timezone.utc)
    existing = (
        await session.exec(select(TimeoutSettings).order_by(TimeoutSettings.setting_key.asc()))
    ).all()
    existing_map = {row.setting_key: row for row in existing}

    for item in payload:
        setting = existing_map.get(item.id)
        if setting is None:
            session.add(
                TimeoutSettings(
                    setting_key=item.id,
                    label=item.label,
                    value=item.value,
                    unit=item.unit,
                    units=item.units,
                    description=item.description,
                    setting_type=item.type,
                    checked=item.checked,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            continue

        setting.label = item.label
        setting.value = item.value
        setting.unit = item.unit
        setting.units = item.units
        setting.description = item.description
        setting.setting_type = item.type
        setting.checked = item.checked
        setting.updated_by = current_user.id
        setting.updated_at = now

    payload_keys = {item.id for item in payload}
    stale_keys = {row.setting_key for row in existing if row.setting_key not in payload_keys}
    if stale_keys:
        await session.exec(delete(TimeoutSettings).where(TimeoutSettings.setting_key.in_(list(stale_keys))))

    await session.commit()

    redis_ttl_setting = next((item for item in payload if item.id == "redis_ttl"), None)
    if redis_ttl_setting is not None:
        redis_ttl_seconds = _parse_redis_ttl_seconds(redis_ttl_setting.value, redis_ttl_setting.unit)
        if redis_ttl_seconds is not None:
            _apply_runtime_redis_ttl(redis_ttl_seconds)

    return {"message": "Timeout settings updated successfully"}
