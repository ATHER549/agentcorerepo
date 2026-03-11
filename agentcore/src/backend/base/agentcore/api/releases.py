from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.package.model import Package
from agentcore.services.database.models.product_release.model import ProductRelease
from agentcore.services.database.models.release_package_snapshot.model import ReleasePackageSnapshot

router = APIRouter(prefix="/releases", tags=["Release Management"])

ACTIVE_END_DATE = date(9999, 12, 31)


class BumpType(str, Enum):
    major = "major"
    minor = "minor"
    patch = "patch"


class ReleaseBumpRequest(BaseModel):
    bump_type: BumpType
    release_notes: str | None = None


def _parse_semver(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid semantic version '{version}'. Expected format: X.Y.Z")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _bump(major: int, minor: int, patch: int, bump_type: BumpType) -> tuple[int, int, int]:
    if bump_type == BumpType.major:
        return major + 1, 0, 0
    if bump_type == BumpType.minor:
        return major, minor + 1, 0
    return major, minor, patch + 1


def _release_to_payload(release: ProductRelease, package_count: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(release.id),
        "version": release.version,
        "major": release.major,
        "minor": release.minor,
        "patch": release.patch,
        "release_notes": release.release_notes or "",
        "start_date": release.start_date.isoformat(),
        "end_date": release.end_date.isoformat(),
        "created_by": str(release.created_by) if release.created_by else None,
        "created_at": release.created_at.isoformat(),
        "updated_at": release.updated_at.isoformat(),
        "is_active": release.end_date == ACTIVE_END_DATE,
    }
    if package_count is not None:
        payload["package_count"] = package_count
    return payload


@router.get("")
@router.get("/")
async def get_releases(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict[str, Any]]:
    releases = (
        await session.exec(
            select(ProductRelease).order_by(ProductRelease.start_date.desc(), ProductRelease.created_at.desc())
        )
    ).all()

    return [_release_to_payload(release) for release in releases]


@router.get("/current")
async def get_current_release(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict[str, Any] | None:
    release = (
        await session.exec(
            select(ProductRelease)
            .where(ProductRelease.end_date == ACTIVE_END_DATE)
            .order_by(ProductRelease.start_date.desc(), ProductRelease.created_at.desc())
        )
    ).first()
    if release is None:
        return None
    return _release_to_payload(release)


@router.post("/bump")
async def bump_release(
    payload: ReleaseBumpRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.date()

    active_release = (
        await session.exec(
            select(ProductRelease)
            .where(ProductRelease.end_date == ACTIVE_END_DATE)
            .order_by(ProductRelease.start_date.desc(), ProductRelease.created_at.desc())
        )
    ).first()

    if active_release:
        try:
            major, minor, patch = _parse_semver(active_release.version)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        major, minor, patch = 0, 0, 0

    next_major, next_minor, next_patch = _bump(major, minor, patch, payload.bump_type)
    next_version = f"{next_major}.{next_minor}.{next_patch}"

    existing = (
        await session.exec(select(ProductRelease).where(ProductRelease.version == next_version))
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Release version '{next_version}' already exists.")

    if active_release is not None:
        active_release.end_date = today
        active_release.updated_at = now

    new_release = ProductRelease(
        version=next_version,
        major=next_major,
        minor=next_minor,
        patch=next_patch,
        release_notes=(payload.release_notes or "").strip() or None,
        start_date=today,
        end_date=ACTIVE_END_DATE,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(new_release)
    await session.flush()

    current_packages = (
        await session.exec(
            select(Package)
            .where(Package.end_date == ACTIVE_END_DATE)
            .order_by(Package.name.asc(), Package.package_type.asc(), Package.synced_at.desc())
        )
    ).all()

    # Defensive deduplication in case older data already has multiple current rows per key.
    seen_keys: set[tuple[str, str]] = set()
    packages: list[Package] = []
    for pkg in current_packages:
        key = (pkg.name.lower(), pkg.package_type)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        packages.append(pkg)

    for pkg in packages:
        session.add(
            ReleasePackageSnapshot(
                release_id=new_release.id,
                name=pkg.name,
                version=pkg.version,
                version_spec=pkg.version_spec,
                package_type=pkg.package_type,
                required_by=pkg.required_by,
                source=pkg.source,
                captured_at=now,
            )
        )
        pkg.release_id = new_release.id

    await session.commit()
    await session.refresh(new_release)

    return _release_to_payload(new_release, package_count=len(packages))
