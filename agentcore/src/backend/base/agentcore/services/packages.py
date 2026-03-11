"""Package sync service – parses pyproject.toml & uv.lock once at startup and stores in DB."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import toml
from loguru import logger
from sqlmodel import select

from agentcore.services.database.models.package.model import Package
from agentcore.services.database.models.product_release.model import ProductRelease
from agentcore.services.deps import session_scope

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # agentcore_clean_code/agentcore
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"
_UV_LOCK = _PROJECT_ROOT / "uv.lock"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """Normalise a Python package name for comparison (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_pyproject_deps() -> list[dict[str, str]]:
    """Read declared dependencies from *pyproject.toml*."""
    if not _PYPROJECT.exists():
        logger.warning("pyproject.toml not found at {}", _PYPROJECT)
        return []

    data = toml.loads(_PYPROJECT.read_text(encoding="utf-8"))
    raw_deps: list[str] = data.get("project", {}).get("dependencies", [])

    results: list[dict[str, str]] = []
    for dep in raw_deps:
        dep_clean = dep.split(";")[0].strip()
        match = re.match(r"^([A-Za-z0-9_][A-Za-z0-9._-]*)(.*)", dep_clean)
        if match:
            name = match.group(1).strip().lower()
            version_spec = match.group(2).strip()
            results.append({"name": name, "version_spec": version_spec})
    return results


def _parse_uv_lock() -> list[dict[str, Any]]:
    """Parse *uv.lock* (TOML) and return the list of resolved packages."""
    if not _UV_LOCK.exists():
        logger.warning("uv.lock not found at {}", _UV_LOCK)
        return []

    data = toml.loads(_UV_LOCK.read_text(encoding="utf-8"))
    return data.get("package", [])


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


async def sync_packages_to_db() -> None:
    """Parse pyproject.toml + uv.lock and SCD-sync the ``package`` table."""
    declared = _parse_pyproject_deps()
    lock_pkgs = _parse_uv_lock()

    if not lock_pkgs:
        logger.warning("No packages found in uv.lock – skipping sync")
        return

    declared_names = {_normalize(d["name"]) for d in declared}

    # Build lookup: normalised-name -> lock entry
    lock_map: dict[str, dict[str, Any]] = {}
    for pkg in lock_pkgs:
        lock_map[_normalize(pkg["name"])] = pkg

    # Build reverse-dependency maps
    required_by_map: dict[str, list[str]] = {}
    required_by_details_map: dict[str, list[dict[str, str]]] = {}
    for pkg in lock_pkgs:
        requester_name = pkg.get("name", "")
        requester_version = pkg.get("version", "unknown")
        for dep in pkg.get("dependencies", []):
            dep_norm = _normalize(dep["name"])
            required_by_map.setdefault(dep_norm, []).append(requester_name)
            required_by_details_map.setdefault(dep_norm, []).append(
                {"name": requester_name, "version": requester_version}
            )

    now = datetime.now(timezone.utc)
    today = now.date()
    open_end_date = date(9999, 12, 31)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()  # (normalised_name, package_type) dedup
    release_id = None

    # Attach latest package sync rows to currently active release, if available.
    try:
        async with session_scope() as session:
            active_release = (
                await session.exec(
                    select(ProductRelease).where(ProductRelease.end_date == date(9999, 12, 31))
                )
            ).first()
            release_id = active_release.id if active_release else None
    except Exception as exc:  # pragma: no cover - defensive only
        logger.debug("Could not resolve active release for package sync: {}", exc)

    # Managed packages (declared in pyproject.toml)
    for dep in declared:
        norm = _normalize(dep["name"])
        key = (norm, "managed")
        if key in seen:
            continue
        seen.add(key)
        lock_entry = lock_map.get(norm, {})
        rows.append(
            {
                "name": dep["name"],
                "version": lock_entry.get("version", "unknown"),
                "version_spec": dep["version_spec"] or None,
                "package_type": "managed",
                "release_id": release_id,
                "required_by": None,
                "required_by_details": None,
                "source": lock_entry.get("source"),
            }
        )

    # Transitive packages (in uv.lock but NOT declared)
    for pkg in lock_pkgs:
        norm = _normalize(pkg["name"])
        if norm in declared_names:
            continue
        source = pkg.get("source", {})
        if isinstance(source, dict) and "editable" in source:
            continue
        key = (norm, "transitive")
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "name": pkg["name"],
                "version": pkg.get("version", "unknown"),
                "version_spec": None,
                "package_type": "transitive",
                "release_id": release_id,
                "required_by": required_by_map.get(norm, []) or None,
                "required_by_details": required_by_details_map.get(norm, []) or None,
                "source": source if source else None,
            }
        )

    async with session_scope() as session:
        current_rows = (
            await session.exec(select(Package).where(Package.end_date == open_end_date))
        ).all()
        current_map = {
            (_normalize(row.name), row.package_type): row
            for row in current_rows
        }

        incoming_keys = set()
        for row in rows:
            key = (_normalize(row["name"]), row["package_type"])
            incoming_keys.add(key)
            existing = current_map.get(key)
            if existing is None:
                session.add(
                    Package(
                        name=row["name"],
                        version=row["version"],
                        version_spec=row["version_spec"],
                        package_type=row["package_type"],
                        release_id=row["release_id"],
                        required_by=row["required_by"],
                        required_by_details=row["required_by_details"],
                        start_date=today,
                        end_date=open_end_date,
                        source=row["source"],
                        synced_at=now,
                    )
                )
                continue

            same_payload = (
                existing.version == row["version"]
                and (existing.version_spec or None) == (row["version_spec"] or None)
                and (existing.required_by or None) == (row["required_by"] or None)
                and (existing.required_by_details or None) == (row["required_by_details"] or None)
                and (existing.source or None) == (row["source"] or None)
            )
            if same_payload:
                existing.synced_at = now
                existing.release_id = row["release_id"]
                continue

            existing.end_date = today
            existing.synced_at = now
            session.add(
                Package(
                    name=row["name"],
                    version=row["version"],
                    version_spec=row["version_spec"],
                    package_type=row["package_type"],
                    release_id=row["release_id"],
                    required_by=row["required_by"],
                    required_by_details=row["required_by_details"],
                    start_date=today,
                    end_date=open_end_date,
                    source=row["source"],
                    synced_at=now,
                )
            )

        # Close packages no longer present in current lock/declaration snapshot.
        for key, existing in current_map.items():
            if key in incoming_keys:
                continue
            existing.end_date = today
            existing.synced_at = now

    logger.info("Synced {} packages to database ({} managed, {} transitive)",
                len(rows),
                sum(1 for r in rows if r["package_type"] == "managed"),
                sum(1 for r in rows if r["package_type"] == "transitive"))
