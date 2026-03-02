"""Dependency governance API – read-only view of managed and transitive packages.

Data is synced from pyproject.toml + uv.lock into the database at application startup.
These endpoints simply read from the ``package`` table.

Endpoints:
    GET /packages/managed    – declared deps with resolved version
    GET /packages/transitive – transitive (indirect) deps with "required by" info
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, DbSession
from agentcore.services.database.models.package.model import Package

router = APIRouter(prefix="/packages", tags=["Packages"])


@router.get("/managed")
async def get_managed_packages(
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[dict[str, Any]]:
    """Return declared dependencies with their resolved version."""
    rows = (
        await session.exec(
            select(Package).where(Package.package_type == "managed")
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
) -> list[dict[str, Any]]:
    """Return transitive (indirect) dependencies."""
    rows = (
        await session.exec(
            select(Package).where(Package.package_type == "transitive")
        )
    ).all()

    return [
        {
            "name": row.name,
            "resolved_version": row.version,
            "required_by": row.required_by or [],
            "source": row.source or {},
        }
        for row in rows
    ]
