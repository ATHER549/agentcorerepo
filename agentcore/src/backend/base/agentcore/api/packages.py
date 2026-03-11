"""Dependency governance API – read-only view of managed and transitive packages.

Data is synced from pyproject.toml + uv.lock into the database at application startup.
These endpoints simply read from the ``package`` table.

Endpoints:
    GET /packages/managed    – declared deps with resolved version
    GET /packages/transitive – transitive (indirect) deps with "required by" info
"""

from __future__ import annotations

from typing import Any

from datetime import date

from fastapi import APIRouter, Query
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.package.model import Package

router = APIRouter(prefix="/packages", tags=["Packages"])
ACTIVE_END_DATE = date(9999, 12, 31)


@router.get("/managed")
async def get_managed_packages(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict[str, Any]]:
    """Return declared dependencies with their resolved version."""
    rows = (
        await session.exec(
            select(Package).where(
                Package.package_type == "managed",
                Package.end_date == ACTIVE_END_DATE,
            )
        )
    ).all()

    return [
        {
            "name": row.name,
            "version_spec": row.version_spec or "",
            "resolved_version": row.version,
            "source": row.source or {},
        }
        for row in rows
    ]


@router.get("/transitive")
async def get_transitive_packages(
    current_user: CurrentActiveUser,
    session: DbSession,
    include_history: bool = Query(default=True),
) -> list[dict[str, Any]]:
    """Return transitive (indirect) dependencies, with history by default."""
    conditions = [Package.package_type == "transitive"]
    if not include_history:
        conditions.append(Package.end_date == ACTIVE_END_DATE)

    rows = (
        await session.exec(
            select(Package)
            .where(*conditions)
            .order_by(Package.name.asc(), Package.start_date.desc(), Package.synced_at.desc())
        )
    ).all()

    return [
        {
            "id": str(row.id),
            "name": row.name,
            "resolved_version": row.version,
            "required_by": row.required_by or [],
            "required_by_details": row.required_by_details or [],
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(),
            "is_current": row.end_date == ACTIVE_END_DATE,
            "source": row.source or {},
        }
        for row in rows
    ]
