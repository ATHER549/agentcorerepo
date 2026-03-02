"""Package sync service – parses pyproject.toml & uv.lock once at startup and stores in DB."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import toml
from loguru import logger
from sqlalchemy import delete
from sqlmodel import select

from agentcore.services.database.models.package.model import Package
from agentcore.services.deps import session_scope

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[5]  # agentcore_clean_code/agentcore
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
    """Parse pyproject.toml + uv.lock and replace all rows in the ``package`` table."""
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

    # Build reverse-dependency map
    required_by_map: dict[str, list[str]] = {}
    for pkg in lock_pkgs:
        for dep in pkg.get("dependencies", []):
            dep_norm = _normalize(dep["name"])
            required_by_map.setdefault(dep_norm, []).append(pkg["name"])

    now = datetime.now(timezone.utc)
    rows: list[Package] = []
    seen: set[tuple[str, str]] = set()  # (normalised_name, package_type) dedup

    # Managed packages (declared in pyproject.toml)
    for dep in declared:
        norm = _normalize(dep["name"])
        key = (norm, "managed")
        if key in seen:
            continue
        seen.add(key)
        lock_entry = lock_map.get(norm, {})
        rows.append(
            Package(
                name=dep["name"],
                version=lock_entry.get("version", "unknown"),
                version_spec=dep["version_spec"] or None,
                package_type="managed",
                required_by=None,
                source=lock_entry.get("source"),
                synced_at=now,
            )
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
            Package(
                name=pkg["name"],
                version=pkg.get("version", "unknown"),
                version_spec=None,
                package_type="transitive",
                required_by=required_by_map.get(norm, []) or None,
                source=source if source else None,
                synced_at=now,
            )
        )

    async with session_scope() as session:
        # Delete old rows and flush so the unique constraint is clear
        await session.exec(delete(Package))  # type: ignore[call-overload]
        await session.flush()
        for row in rows:
            session.add(row)

    logger.info("Synced {} packages to database ({} managed, {} transitive)",
                len(rows),
                sum(1 for r in rows if r.package_type == "managed"),
                sum(1 for r in rows if r.package_type == "transitive"))
