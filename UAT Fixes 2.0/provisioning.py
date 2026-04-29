from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.database.models.department.model import Department
from agentcore.services.database.models.langfuse_binding.model import LangfuseBinding
from agentcore.services.database.models.observability_provision_job.model import ObservabilityProvisionJob
from agentcore.services.database.models.observability_schema_lock.model import ObservabilitySchemaLock
from agentcore.services.database.models.organization.model import Organization
from agentcore.services.database.models.user.model import User
from agentcore.services.auth.permissions import normalize_role


class LangfuseProvisioningError(RuntimeError):
    """Raised when Langfuse provisioning fails."""


# Hardening for the internal raw-SQL insert helpers
# (_insert_row / _insert_row_returning_id). Identifiers (table + column
# names) can't be bound by SQLAlchemy parameter binding — they must be
# string-interpolated — so we enforce two invariants before interpolation:
#   1. table_name must be in a fixed allowlist, and
#   2. every column identifier must match a strict regex.
# Values are always bound via :name parameters and never interpolated,
# so they remain safe against SQL injection. Callers today pass only
# hardcoded table literals and programmatic payloads, so this change is
# purely defense-in-depth against future misuse.
_ALLOWED_LANGFUSE_TABLES: frozenset[str] = frozenset({
    "organizations",
    "organization_memberships",
    "projects",
    "project_memberships",
    "api_keys",
})

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class ProvisioningResult:
    langfuse_org_id: str
    langfuse_project_id: str
    langfuse_project_name: str
    public_key: str
    secret_key: str
    schema_fingerprint: str
    api_key_id: str
    created_org: bool
    created_project: bool


@dataclass
class BindingReconciliationResult:
    binding_id: str
    status: str
    issues: list[str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_fernet_key(raw_key: str) -> str:
    key = (raw_key or "").strip()
    if not key:
        key = os.getenv("MODEL_REGISTRY_ENCRYPTION_KEY", "").strip()
    if not key:
        key = os.getenv("WEBUI_SECRET_KEY", "").strip()
    if not key:
        key = "default-observability-encryption-key"

    try:
        # Already a valid fernet key
        Fernet(key.encode())
        return key
    except Exception:
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8")


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


class LangfuseProvisioningService:
    """Provision Langfuse org/project/api-key by direct DB writes."""

    REQUIRED_TABLE_COLUMNS: dict[str, set[str]] = {
        "organizations": {"id", "name"},
        "users": {"id"},
        "projects": {"id", "name"},
        "api_keys": {"id", "public_key", "hashed_secret_key", "fast_hashed_secret_key"},
        "organization_memberships": {"id"},
    }

    def __init__(self) -> None:
        self.langfuse_db_url = os.getenv("LANGFUSE_DB_URL", "").strip()
        self.langfuse_host = os.getenv("LANGFUSE_HOST", "").strip() or os.getenv("LANGFUSE_BASE_URL", "").strip()
        self.bootstrap_email = os.getenv("LANGFUSE_BOOTSTRAP_USER_EMAIL", "").strip()
        self.schema_lock = os.getenv("LANGFUSE_SCHEMA_LOCK", "").strip()
        self.schema_version_tag = os.getenv("LANGFUSE_SCHEMA_VERSION_TAG", "").strip() or "current-local"
        self.hash_strategy_version = os.getenv("LANGFUSE_HASH_STRATEGY_VERSION", "").strip() or "v1"
        self.langfuse_salt = os.getenv("LANGFUSE_SALT", "").strip()
        self.encryption_key = _ensure_fernet_key(os.getenv("OBSERVABILITY_ENCRYPTION_KEY", "").strip())

    @property
    def enabled(self) -> bool:
        return str(os.getenv("OBS_PROVISIONING_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}

    def encrypt_secret(self, value: str) -> str:
        return Fernet(self.encryption_key.encode()).encrypt(value.encode()).decode()

    def decrypt_secret(self, encrypted: str) -> str:
        return Fernet(self.encryption_key.encode()).decrypt(encrypted.encode()).decode()

    async def ensure_root_private_binding(
        self,
        session: AsyncSession,
        *,
        actor: User,
    ) -> LangfuseBinding:
        """Ensure a dedicated root-private org-admin binding exists.

        Used when root executes private/unscoped agents (no org/dept association).
        """
        role = normalize_role(getattr(actor, "role", None))
        if role != "root":
            raise LangfuseProvisioningError("Root-private observability binding is only available for root role.")

        root_org_name = (os.getenv("OBS_ROOT_PRIVATE_ORG_NAME", "__root_observability__") or "").strip()
        if not root_org_name:
            root_org_name = "__root_observability__"
        root_org_description = (
            os.getenv(
                "OBS_ROOT_PRIVATE_ORG_DESCRIPTION",
                "Reserved organization for root-private observability tracing.",
            )
            or "Reserved organization for root-private observability tracing."
        ).strip()

        org = (
            await session.exec(
                select(Organization).where(Organization.name == root_org_name)
            )
        ).first()
        if org is None:
            org = Organization(
                name=root_org_name,
                description=root_org_description,
                owner_user_id=actor.id,
                created_by=actor.id,
                updated_by=actor.id,
            )
            session.add(org)
            await session.flush()

        return await self.provision_org_admin_project(
            session,
            org=org,
            actor=actor,
            idempotency_key=f"root-private-org:{org.id}",
        )

    async def provision_org_admin_project(
        self,
        session: AsyncSession,
        *,
        org: Organization,
        actor: User,
        idempotency_key: str | None = None,
    ) -> LangfuseBinding:
        return await self._provision_scope(
            session,
            scope_type="org_admin",
            org=org,
            department=None,
            actor=actor,
            idempotency_key=idempotency_key or f"org-admin:{org.id}",
            project_name=f"{org.name}-admin-observability",
        )

    async def provision_department_project(
        self,
        session: AsyncSession,
        *,
        org: Organization,
        department: Department,
        actor: User,
        idempotency_key: str | None = None,
    ) -> LangfuseBinding:
        return await self._provision_scope(
            session,
            scope_type="department",
            org=org,
            department=department,
            actor=actor,
            idempotency_key=idempotency_key or f"department:{department.id}",
            project_name=f"{department.name}-observability",
        )

    async def _provision_scope(
        self,
        session: AsyncSession,
        *,
        scope_type: str,
        org: Organization,
        department: Department | None,
        actor: User,
        idempotency_key: str,
        project_name: str,
    ) -> LangfuseBinding:
        if not self.enabled:
            raise LangfuseProvisioningError("OBS_PROVISIONING_ENABLED is false.")
        if not self.langfuse_db_url:
            raise LangfuseProvisioningError("LANGFUSE_DB_URL is not configured.")
        if not self.langfuse_host:
            raise LangfuseProvisioningError("LANGFUSE_HOST/LANGFUSE_BASE_URL is not configured.")
        if not self.bootstrap_email:
            raise LangfuseProvisioningError("LANGFUSE_BOOTSTRAP_USER_EMAIL is not configured.")

        existing_binding_stmt = select(LangfuseBinding).where(
            LangfuseBinding.scope_type == scope_type,
            LangfuseBinding.org_id == org.id,
            LangfuseBinding.is_active.is_(True),
        )
        if department is not None:
            existing_binding_stmt = existing_binding_stmt.where(LangfuseBinding.dept_id == department.id)
        else:
            existing_binding_stmt = existing_binding_stmt.where(LangfuseBinding.dept_id.is_(None))
        existing_binding = (await session.exec(existing_binding_stmt)).first()
        if existing_binding:
            return existing_binding

        payload_hash = hashlib.sha256(
            f"{scope_type}:{org.id}:{department.id if department else ''}:{project_name}".encode("utf-8")
        ).hexdigest()
        job = await self._get_or_create_job(
            session=session,
            idempotency_key=idempotency_key,
            scope_type=scope_type,
            org_id=org.id,
            dept_id=department.id if department else None,
            payload_hash=payload_hash,
            actor_id=actor.id,
        )
        job.status = "running"
        job.started_at = _utc_now()
        job.updated_at = _utc_now()
        job.retry_count = int(job.retry_count or 0)
        session.add(job)
        await session.flush()

        try:
            result = await asyncio.to_thread(
                self._provision_scope_sync,
                scope_type=scope_type,
                app_org_id=str(org.id),
                app_org_name=str(org.name),
                app_dept_id=str(department.id) if department else None,
                project_name=project_name,
            )
            try:
                await asyncio.to_thread(
                    self._verify_langfuse_credentials,
                    result.public_key,
                    result.secret_key,
                )
            except Exception as verify_exc:
                try:
                    await asyncio.to_thread(self._cleanup_failed_provision_sync, result)
                except Exception:
                    logger.exception(
                        "Langfuse cleanup failed after verification error for org={} dept={} scope={}",
                        org.id,
                        department.id if department else None,
                        scope_type,
                    )
                raise LangfuseProvisioningError(
                    f"Generated Langfuse credentials failed verification for scope={scope_type}."
                ) from verify_exc

            binding = LangfuseBinding(
                org_id=org.id,
                dept_id=department.id if department else None,
                scope_type=scope_type,
                langfuse_org_id=result.langfuse_org_id,
                langfuse_project_id=result.langfuse_project_id,
                langfuse_project_name=result.langfuse_project_name,
                langfuse_host=self.langfuse_host,
                public_key_encrypted=self.encrypt_secret(result.public_key),
                secret_key_encrypted=self.encrypt_secret(result.secret_key),
                is_active=True,
                created_by=actor.id,
                updated_by=actor.id,
            )
            session.add(binding)

            schema_lock_row = (
                await session.exec(
                    select(ObservabilitySchemaLock).where(
                        ObservabilitySchemaLock.version_tag == self.schema_version_tag
                    )
                )
            ).first()
            if schema_lock_row:
                schema_lock_row.schema_fingerprint = result.schema_fingerprint
                schema_lock_row.validated_at = _utc_now()
                session.add(schema_lock_row)
            else:
                session.add(
                    ObservabilitySchemaLock(
                        version_tag=self.schema_version_tag,
                        schema_fingerprint=result.schema_fingerprint,
                        validated_at=_utc_now(),
                    )
                )

            job.status = "success"
            job.error_message = None
            job.finished_at = _utc_now()
            job.updated_at = _utc_now()
            session.add(job)
            await session.flush()
            return binding
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = _utc_now()
            job.updated_at = _utc_now()
            job.retry_count = int(job.retry_count or 0) + 1
            session.add(job)
            await session.flush()
            raise

    async def _get_or_create_job(
        self,
        *,
        session: AsyncSession,
        idempotency_key: str,
        scope_type: str,
        org_id: UUID | None,
        dept_id: UUID | None,
        payload_hash: str,
        actor_id: UUID | None,
    ) -> ObservabilityProvisionJob:
        existing = (
            await session.exec(
                select(ObservabilityProvisionJob).where(
                    ObservabilityProvisionJob.idempotency_key == idempotency_key
                )
            )
        ).first()
        if existing:
            return existing
        job = ObservabilityProvisionJob(
            idempotency_key=idempotency_key,
            scope_type=scope_type,
            org_id=org_id,
            dept_id=dept_id,
            payload_hash=payload_hash,
            status="pending",
            created_by=actor_id,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        session.add(job)
        await session.flush()
        return job

    def _provision_scope_sync(
        self,
        *,
        scope_type: str,
        app_org_id: str,
        app_org_name: str,
        app_dept_id: str | None,
        project_name: str,
    ) -> ProvisioningResult:
        sync_db_url = self._to_sync_db_url(self.langfuse_db_url)
        engine = create_engine(sync_db_url, future=True)
        try:
            with engine.begin() as conn:
                table_columns = self._get_table_columns(conn)
                schema_fingerprint = self._validate_schema_lock(table_columns)

                bootstrap_user_id = self._fetch_bootstrap_user_id(conn, table_columns)
                existing_org_id = self._lookup_existing_organization_id(
                    conn=conn,
                    org_id=app_org_id,
                    org_name=app_org_name,
                )
                langfuse_org_id = self._ensure_organization(
                    conn=conn,
                    table_columns=table_columns,
                    org_id=app_org_id,
                    org_name=app_org_name,
                )
                org_created = existing_org_id is None
                org_membership_id = self._ensure_org_membership(
                    conn=conn,
                    table_columns=table_columns,
                    org_id=langfuse_org_id,
                    user_id=bootstrap_user_id,
                )

                target_project_id = app_dept_id if scope_type == "department" and app_dept_id else str(uuid.uuid4())
                existing_project_id = self._lookup_existing_project_id(
                    conn=conn,
                    table_columns=table_columns,
                    project_id=target_project_id,
                    org_id=langfuse_org_id,
                    project_name=project_name,
                )
                langfuse_project_id = self._ensure_project(
                    conn=conn,
                    table_columns=table_columns,
                    project_id=target_project_id,
                    org_id=langfuse_org_id,
                    project_name=project_name,
                )
                project_created = existing_project_id is None
                self._ensure_project_membership(
                    conn=conn,
                    table_columns=table_columns,
                    project_id=langfuse_project_id,
                    user_id=bootstrap_user_id,
                    org_membership_id=org_membership_id,
                )

                public_key, secret_key = self._generate_api_keys()
                hashed_secret_key, fast_hashed_secret_key = self._hash_secret(secret_key)
                api_key_id = self._insert_api_key(
                    conn=conn,
                    table_columns=table_columns,
                    project_id=langfuse_project_id,
                    org_id=langfuse_org_id,
                    public_key=public_key,
                    secret_key=secret_key,
                    hashed_secret_key=hashed_secret_key,
                    fast_hashed_secret_key=fast_hashed_secret_key,
                )

                return ProvisioningResult(
                    langfuse_org_id=langfuse_org_id,
                    langfuse_project_id=langfuse_project_id,
                    langfuse_project_name=project_name,
                    public_key=public_key,
                    secret_key=secret_key,
                    schema_fingerprint=schema_fingerprint,
                    api_key_id=api_key_id,
                    created_org=org_created,
                    created_project=project_created,
                )
        finally:
            engine.dispose()

    def _cleanup_failed_provision_sync(self, result: ProvisioningResult) -> None:
        sync_db_url = self._to_sync_db_url(self.langfuse_db_url)
        engine = create_engine(sync_db_url, future=True)
        try:
            with engine.begin() as conn:
                table_columns = self._get_table_columns(conn)
                if "api_keys" in table_columns:
                    conn.execute(
                        text("DELETE FROM api_keys WHERE id = :id"),
                        {"id": result.api_key_id},
                    )

                if result.created_project and "projects" in table_columns:
                    if "project_memberships" in table_columns:
                        conn.execute(
                            text("DELETE FROM project_memberships WHERE project_id = :project_id"),
                            {"project_id": result.langfuse_project_id},
                        )
                    conn.execute(
                        text("DELETE FROM projects WHERE id = :id"),
                        {"id": result.langfuse_project_id},
                    )

                if result.created_org and "organizations" in table_columns:
                    if "organization_memberships" in table_columns:
                        org_membership_cols = table_columns.get("organization_memberships", set())
                        membership_org_col = self._first_column_match(
                            org_membership_cols,
                            ("organization_id", "org_id"),
                        )
                        if not membership_org_col:
                            raise LangfuseProvisioningError(
                                "organization_memberships table missing organization reference column (organization_id/org_id)."
                            )
                        conn.execute(
                            text(f"DELETE FROM organization_memberships WHERE {membership_org_col} = :org_id"),
                            {"org_id": result.langfuse_org_id},
                        )
                    projects_cols = table_columns.get("projects", set())
                    project_org_col = self._first_column_match(
                        projects_cols,
                        ("organization_id", "org_id"),
                    )
                    if not project_org_col:
                        raise LangfuseProvisioningError(
                            "projects table missing organization reference column (organization_id/org_id)."
                        )
                    conn.execute(
                        text(
                            "DELETE FROM organizations WHERE id = :id "
                            f"AND NOT EXISTS (SELECT 1 FROM projects WHERE {project_org_col} = :id)"
                        ),
                        {"id": result.langfuse_org_id},
                    )
        finally:
            engine.dispose()

    @staticmethod
    def _to_sync_db_url(url: str) -> str:
        if url.startswith("postgresql+asyncpg://"):
            return "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
        if url.startswith("postgresql+psycopg://"):
            return url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        return url

    def _get_table_columns(self, conn: Connection) -> dict[str, set[str]]:
        rows = conn.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                """
            )
        ).fetchall()
        result: dict[str, set[str]] = {}
        for table_name, column_name in rows:
            result.setdefault(str(table_name), set()).add(str(column_name))
        return result

    def _validate_schema_lock(self, table_columns: dict[str, set[str]]) -> str:
        for table_name, required_columns in self.REQUIRED_TABLE_COLUMNS.items():
            cols = table_columns.get(table_name, set())
            missing = required_columns - cols
            if missing:
                raise LangfuseProvisioningError(
                    f"Langfuse schema mismatch for {table_name}: missing columns {sorted(missing)}"
                )

        parts: list[str] = []
        for table_name in sorted(self.REQUIRED_TABLE_COLUMNS):
            cols = sorted(table_columns.get(table_name, set()))
            parts.append(f"{table_name}:{','.join(cols)}")
        fingerprint = hashlib.sha256(";".join(parts).encode("utf-8")).hexdigest()

        if self.schema_lock and self.schema_lock != fingerprint:
            raise LangfuseProvisioningError(
                f"LANGFUSE_SCHEMA_LOCK mismatch. expected={self.schema_lock}, actual={fingerprint}"
            )
        return fingerprint

    def _fetch_bootstrap_user_id(self, conn: Connection, table_columns: dict[str, set[str]]) -> str:
        user_cols = table_columns.get("users", set())
        if "email" in user_cols:
            row = conn.execute(
                text("SELECT id FROM users WHERE email = :email LIMIT 1"),
                {"email": self.bootstrap_email},
            ).fetchone()
            if row:
                return str(row[0])
        if "username" in user_cols:
            row = conn.execute(
                text("SELECT id FROM users WHERE username = :username LIMIT 1"),
                {"username": self.bootstrap_email},
            ).fetchone()
            if row:
                return str(row[0])
        raise LangfuseProvisioningError(
            f"Bootstrap Langfuse user not found for LANGFUSE_BOOTSTRAP_USER_EMAIL={self.bootstrap_email}"
        )

    def _ensure_organization(
        self,
        *,
        conn: Connection,
        table_columns: dict[str, set[str]],
        org_id: str,
        org_name: str,
    ) -> str:
        row = conn.execute(
            text("SELECT id FROM organizations WHERE id = :id OR name = :name ORDER BY created_at NULLS LAST LIMIT 1"),
            {"id": org_id, "name": org_name},
        ).fetchone()
        if row:
            return str(row[0])

        now = _utc_now()
        payload: dict[str, Any] = {"id": org_id, "name": org_name, "created_at": now, "updated_at": now}
        cols = table_columns.get("organizations", set())
        return self._insert_row_returning_id(conn, "organizations", payload, cols)

    def _lookup_existing_organization_id(self, *, conn: Connection, org_id: str, org_name: str) -> str | None:
        row = conn.execute(
            text("SELECT id FROM organizations WHERE id = :id OR name = :name ORDER BY created_at NULLS LAST LIMIT 1"),
            {"id": org_id, "name": org_name},
        ).fetchone()
        if not row:
            return None
        return str(row[0])

    def _ensure_org_membership(
        self,
        *,
        conn: Connection,
        table_columns: dict[str, set[str]],
        org_id: str,
        user_id: str,
    ) -> str | None:
        if "organization_memberships" not in table_columns:
            return None
        cols = table_columns["organization_memberships"]
        org_ref_col = self._first_column_match(cols, ("organization_id", "org_id"))
        if not org_ref_col:
            raise LangfuseProvisioningError(
                "organization_memberships table missing organization reference column (organization_id/org_id)."
            )
        has_id_col = "id" in cols
        row = conn.execute(
            text(
                f"SELECT {'id' if has_id_col else '1'} FROM organization_memberships "
                f"WHERE {org_ref_col} = :org_id AND user_id = :user_id LIMIT 1"
            ),
            {"org_id": org_id, "user_id": user_id},
        ).fetchone()
        if row:
            return str(row[0]) if has_id_col else None
        now = _utc_now()
        payload: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            org_ref_col: org_id,
            "user_id": user_id,
            "role": "OWNER",
            "created_at": now,
            "updated_at": now,
        }
        self._insert_row(conn, "organization_memberships", payload, cols)
        return str(payload["id"]) if has_id_col else None

    def _ensure_project(
        self,
        *,
        conn: Connection,
        table_columns: dict[str, set[str]],
        project_id: str,
        org_id: str,
        project_name: str,
    ) -> str:
        cols = table_columns["projects"]
        org_ref_col = self._first_column_match(cols, ("organization_id", "org_id"))
        if not org_ref_col:
            raise LangfuseProvisioningError(
                "projects table missing organization reference column (organization_id/org_id)."
            )
        row = conn.execute(
            text(
                f"SELECT id FROM projects WHERE id = :id OR ({org_ref_col} = :org_id AND name = :name) "
                "ORDER BY created_at NULLS LAST LIMIT 1"
            ),
            {"id": project_id, "org_id": org_id, "name": project_name},
        ).fetchone()
        if row:
            return str(row[0])

        now = _utc_now()
        payload: dict[str, Any] = {
            "id": project_id,
            "name": project_name,
            org_ref_col: org_id,
            "created_at": now,
            "updated_at": now,
        }
        return self._insert_row_returning_id(conn, "projects", payload, cols)

    def _lookup_existing_project_id(
        self,
        *,
        conn: Connection,
        table_columns: dict[str, set[str]],
        project_id: str,
        org_id: str,
        project_name: str,
    ) -> str | None:
        cols = table_columns.get("projects", set())
        org_ref_col = self._first_column_match(cols, ("organization_id", "org_id"))
        if not org_ref_col:
            raise LangfuseProvisioningError(
                "projects table missing organization reference column (organization_id/org_id)."
            )
        row = conn.execute(
            text(
                f"SELECT id FROM projects WHERE id = :id OR ({org_ref_col} = :org_id AND name = :name) "
                "ORDER BY created_at NULLS LAST LIMIT 1"
            ),
            {"id": project_id, "org_id": org_id, "name": project_name},
        ).fetchone()
        if not row:
            return None
        return str(row[0])

    def _ensure_project_membership(
        self,
        *,
        conn: Connection,
        table_columns: dict[str, set[str]],
        project_id: str,
        user_id: str,
        org_membership_id: str | None = None,
    ) -> None:
        if "project_memberships" not in table_columns:
            return
        cols = table_columns["project_memberships"]
        row = conn.execute(
            text("SELECT 1 FROM project_memberships WHERE project_id = :project_id AND user_id = :user_id LIMIT 1"),
            {"project_id": project_id, "user_id": user_id},
        ).fetchone()
        if row:
            return
        now = _utc_now()
        if "org_membership_id" in cols and not org_membership_id:
            raise LangfuseProvisioningError(
                "project_memberships.org_membership_id is required but organization membership id is unavailable."
            )
        payload: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "user_id": user_id,
            "org_membership_id": org_membership_id,
            "role": "OWNER",
            "created_at": now,
            "updated_at": now,
        }
        self._insert_row(conn, "project_memberships", payload, cols)

    def _insert_api_key(
        self,
        *,
        conn: Connection,
        table_columns: dict[str, set[str]],
        project_id: str,
        org_id: str,
        public_key: str,
        secret_key: str,
        hashed_secret_key: str,
        fast_hashed_secret_key: str,
    ) -> str:
        now = _utc_now()
        cols = table_columns["api_keys"]
        api_key_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "id": api_key_id,
            "public_key": public_key,
            "hashed_secret_key": hashed_secret_key,
            "fast_hashed_secret_key": fast_hashed_secret_key,
            "display_secret_key": _mask_key(secret_key),
            "project_id": project_id,
            "organization_id": org_id,
            "scope": "PROJECT",
            "note": "provisioned-by-agentcore",
            "created_at": now,
            "updated_at": now,
        }
        self._insert_row(conn, "api_keys", payload, cols)
        return api_key_id

    @staticmethod
    def _prepare_safe_insert(
        conn: Connection,
        table_name: str,
        payload: dict[str, Any],
        table_columns: set[str],
    ) -> tuple[str, str, str, dict[str, Any]]:
        """Validate identifiers and return quoted SQL fragments for an INSERT.

        Returns ``(quoted_table, quoted_cols_csv, bind_placeholders_csv,
        effective_payload)``. Raises ``LangfuseProvisioningError`` on any
        untrusted table, invalid column identifier, or empty effective
        payload.

        Values go through SQLAlchemy bind parameters (``:name``) and are
        never interpolated; only identifiers are interpolated, and only
        after the allowlist + regex + dialect-level quoting below.
        """
        if table_name not in _ALLOWED_LANGFUSE_TABLES:
            raise LangfuseProvisioningError(
                f"Refusing to insert into untrusted table={table_name!r}"
            )

        effective_payload = {k: v for k, v in payload.items() if k in table_columns}
        if not effective_payload:
            raise LangfuseProvisioningError(
                f"No compatible columns found for table={table_name}"
            )

        for col in effective_payload:
            if not _SQL_IDENTIFIER_RE.match(col):
                raise LangfuseProvisioningError(
                    f"Invalid column identifier for table={table_name}: {col!r}"
                )

        preparer = conn.dialect.identifier_preparer
        quoted_table = preparer.quote(table_name)
        quoted_cols = ", ".join(preparer.quote(c) for c in effective_payload)
        bind_names = ", ".join(f":{c}" for c in effective_payload)
        return quoted_table, quoted_cols, bind_names, effective_payload

    @staticmethod
    def _insert_row(conn: Connection, table_name: str, payload: dict[str, Any], table_columns: set[str]) -> None:
        quoted_table, quoted_cols, bind_names, effective_payload = (
            LangfuseProvisioningService._prepare_safe_insert(
                conn, table_name, payload, table_columns,
            )
        )
        conn.execute(
            text(f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES ({bind_names})"),
            effective_payload,
        )

    def _insert_row_returning_id(
        self,
        conn: Connection,
        table_name: str,
        payload: dict[str, Any],
        table_columns: set[str],
    ) -> str:
        quoted_table, quoted_cols, bind_names, effective_payload = self._prepare_safe_insert(
            conn, table_name, payload, table_columns,
        )
        row = conn.execute(
            text(
                f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES ({bind_names}) RETURNING id"
            ),
            effective_payload,
        ).fetchone()
        if not row:
            raise LangfuseProvisioningError(f"Failed to insert row in table={table_name}")
        return str(row[0])

    @staticmethod
    def _generate_api_keys() -> tuple[str, str]:
        public_key = f"pk-lf-{secrets.token_hex(16)}"
        secret_key = f"sk-lf-{secrets.token_hex(24)}"
        return public_key, secret_key

    def _hash_secret(self, secret_key: str) -> tuple[str, str]:
        try:
            import bcrypt
        except Exception as exc:
            raise LangfuseProvisioningError(
                "bcrypt dependency is required for Langfuse key hashing."
            ) from exc

        hashed_secret_key = bcrypt.hashpw(secret_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        # Must match Langfuse's createShaHash(privateKey, salt):
        #   SHA256(privateKey + SHA256_hex(salt))
        # See: langfuse/packages/shared/src/server/auth/apiKeys.ts
        salt_hash_hex = hashlib.sha256(self.langfuse_salt.encode("utf-8")).hexdigest()
        fast_hashed_secret_key = hashlib.sha256(
            (secret_key + salt_hash_hex).encode("utf-8")
        ).hexdigest()
        return hashed_secret_key, fast_hashed_secret_key

    def _verify_langfuse_credentials(self, public_key: str, secret_key: str) -> None:
        try:
            from langfuse import Langfuse
        except Exception as exc:
            raise LangfuseProvisioningError(
                "langfuse package not installed; cannot verify generated credentials."
            ) from exc

        client = Langfuse(secret_key=secret_key, public_key=public_key, host=self.langfuse_host)
        if hasattr(client, "auth_check"):
            ok = bool(client.auth_check())
            if not ok:
                raise LangfuseProvisioningError("Generated Langfuse key verification failed (auth_check=false).")

    # ── Langfuse delete helpers ───────────────────────────────────────

    async def cleanup_department_langfuse(
        self,
        session: AsyncSession,
        *,
        dept_id: UUID,
    ) -> None:
        """Delete the Langfuse project mapped to a department and deactivate its binding."""
        if not self.enabled or not self.langfuse_db_url:
            return
        binding = (
            await session.exec(
                select(LangfuseBinding).where(
                    LangfuseBinding.dept_id == dept_id,
                    LangfuseBinding.scope_type == "department",
                    LangfuseBinding.is_active.is_(True),
                )
            )
        ).first()
        if not binding:
            return
        try:
            await asyncio.to_thread(
                self._delete_langfuse_project_sync,
                langfuse_project_id=binding.langfuse_project_id,
                langfuse_org_id=binding.langfuse_org_id,
            )
        except Exception:
            logger.exception(
                "Failed to delete Langfuse project for dept_id={}", dept_id,
            )
        binding.is_active = False
        binding.updated_at = _utc_now()
        session.add(binding)

    async def cleanup_org_admin_langfuse(
        self,
        session: AsyncSession,
        *,
        org_id: UUID,
    ) -> None:
        """Delete the Langfuse org-admin project and (if empty) the org itself; deactivate binding."""
        if not self.enabled or not self.langfuse_db_url:
            return
        binding = (
            await session.exec(
                select(LangfuseBinding).where(
                    LangfuseBinding.org_id == org_id,
                    LangfuseBinding.scope_type == "org_admin",
                    LangfuseBinding.dept_id.is_(None),
                    LangfuseBinding.is_active.is_(True),
                )
            )
        ).first()
        if not binding:
            return
        try:
            await asyncio.to_thread(
                self._delete_langfuse_project_sync,
                langfuse_project_id=binding.langfuse_project_id,
                langfuse_org_id=binding.langfuse_org_id,
            )
            await asyncio.to_thread(
                self._delete_langfuse_org_sync,
                langfuse_org_id=binding.langfuse_org_id,
            )
        except Exception:
            logger.exception(
                "Failed to delete Langfuse org-admin artefacts for org_id={}", org_id,
            )
        binding.is_active = False
        binding.updated_at = _utc_now()
        session.add(binding)

    def _delete_langfuse_project_sync(
        self,
        *,
        langfuse_project_id: str,
        langfuse_org_id: str,
    ) -> None:
        sync_db_url = self._to_sync_db_url(self.langfuse_db_url)
        engine = create_engine(sync_db_url, future=True)
        try:
            with engine.begin() as conn:
                table_columns = self._get_table_columns(conn)
                if "api_keys" in table_columns:
                    conn.execute(
                        text("DELETE FROM api_keys WHERE project_id = :project_id"),
                        {"project_id": langfuse_project_id},
                    )
                if "project_memberships" in table_columns:
                    conn.execute(
                        text("DELETE FROM project_memberships WHERE project_id = :project_id"),
                        {"project_id": langfuse_project_id},
                    )
                if "projects" in table_columns:
                    conn.execute(
                        text("DELETE FROM projects WHERE id = :id"),
                        {"id": langfuse_project_id},
                    )
        finally:
            engine.dispose()

    def _delete_langfuse_org_sync(self, *, langfuse_org_id: str) -> None:
        """Delete a Langfuse organization only when it has no remaining projects."""
        sync_db_url = self._to_sync_db_url(self.langfuse_db_url)
        engine = create_engine(sync_db_url, future=True)
        try:
            with engine.begin() as conn:
                table_columns = self._get_table_columns(conn)
                projects_cols = table_columns.get("projects", set())
                project_org_col = self._first_column_match(
                    projects_cols, ("organization_id", "org_id"),
                )
                if not project_org_col:
                    return
                if "organization_memberships" in table_columns:
                    org_membership_cols = table_columns.get("organization_memberships", set())
                    membership_org_col = self._first_column_match(
                        org_membership_cols, ("organization_id", "org_id"),
                    )
                    if membership_org_col:
                        conn.execute(
                            text(
                                f"DELETE FROM organization_memberships "
                                f"WHERE {membership_org_col} = :org_id "
                                f"AND NOT EXISTS ("
                                f"  SELECT 1 FROM projects WHERE {project_org_col} = :org_id"
                                f")"
                            ),
                            {"org_id": langfuse_org_id},
                        )
                conn.execute(
                    text(
                        f"DELETE FROM organizations WHERE id = :id "
                        f"AND NOT EXISTS (SELECT 1 FROM projects WHERE {project_org_col} = :id)"
                    ),
                    {"id": langfuse_org_id},
                )
        finally:
            engine.dispose()

    # ── Langfuse rename helpers ───────────────────────────────────────

    async def rename_org_in_langfuse(
        self,
        session: AsyncSession,
        *,
        org_id: UUID,
        new_name: str,
    ) -> None:
        """Rename the Langfuse organization and its org-admin project."""
        if not self.enabled or not self.langfuse_db_url:
            return
        binding = (
            await session.exec(
                select(LangfuseBinding).where(
                    LangfuseBinding.org_id == org_id,
                    LangfuseBinding.scope_type == "org_admin",
                    LangfuseBinding.dept_id.is_(None),
                    LangfuseBinding.is_active.is_(True),
                )
            )
        ).first()
        if not binding:
            return
        new_project_name = f"{new_name}-admin-observability"
        try:
            await asyncio.to_thread(
                self._rename_langfuse_org_sync,
                langfuse_org_id=binding.langfuse_org_id,
                new_org_name=new_name,
            )
            await asyncio.to_thread(
                self._rename_langfuse_project_sync,
                langfuse_project_id=binding.langfuse_project_id,
                new_project_name=new_project_name,
            )
        except Exception:
            logger.exception(
                "Failed to rename Langfuse artefacts for org_id={}", org_id,
            )
            raise LangfuseProvisioningError(
                f"Failed to rename Langfuse organization/project for org_id={org_id}"
            )
        binding.langfuse_project_name = new_project_name
        binding.updated_at = _utc_now()
        session.add(binding)

    async def rename_department_in_langfuse(
        self,
        session: AsyncSession,
        *,
        dept_id: UUID,
        new_name: str,
    ) -> None:
        """Rename the Langfuse project mapped to a department."""
        if not self.enabled or not self.langfuse_db_url:
            return
        binding = (
            await session.exec(
                select(LangfuseBinding).where(
                    LangfuseBinding.dept_id == dept_id,
                    LangfuseBinding.scope_type == "department",
                    LangfuseBinding.is_active.is_(True),
                )
            )
        ).first()
        if not binding:
            return
        new_project_name = f"{new_name}-observability"
        try:
            await asyncio.to_thread(
                self._rename_langfuse_project_sync,
                langfuse_project_id=binding.langfuse_project_id,
                new_project_name=new_project_name,
            )
        except Exception:
            logger.exception(
                "Failed to rename Langfuse project for dept_id={}", dept_id,
            )
            raise LangfuseProvisioningError(
                f"Failed to rename Langfuse project for dept_id={dept_id}"
            )
        binding.langfuse_project_name = new_project_name
        binding.updated_at = _utc_now()
        session.add(binding)

    def _rename_langfuse_org_sync(self, *, langfuse_org_id: str, new_org_name: str) -> None:
        sync_db_url = self._to_sync_db_url(self.langfuse_db_url)
        engine = create_engine(sync_db_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE organizations SET name = :name, updated_at = :now WHERE id = :id"),
                    {"name": new_org_name, "now": _utc_now(), "id": langfuse_org_id},
                )
        finally:
            engine.dispose()

    def _rename_langfuse_project_sync(self, *, langfuse_project_id: str, new_project_name: str) -> None:
        sync_db_url = self._to_sync_db_url(self.langfuse_db_url)
        engine = create_engine(sync_db_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE projects SET name = :name, updated_at = :now WHERE id = :id"),
                    {"name": new_project_name, "now": _utc_now(), "id": langfuse_project_id},
                )
        finally:
            engine.dispose()

    def reconcile_bindings(self, bindings: list[LangfuseBinding]) -> list[BindingReconciliationResult]:
        """Detect drift between Agentcore bindings and Langfuse DB rows."""
        if not self.langfuse_db_url:
            raise LangfuseProvisioningError("LANGFUSE_DB_URL is not configured.")

        sync_db_url = self._to_sync_db_url(self.langfuse_db_url)
        engine = create_engine(sync_db_url, future=True)
        try:
            with engine.connect() as conn:
                table_columns = self._get_table_columns(conn)
                required_tables = {"organizations", "projects", "api_keys"}
                missing_tables = [name for name in sorted(required_tables) if name not in table_columns]
                if missing_tables:
                    raise LangfuseProvisioningError(
                        f"Langfuse schema mismatch: missing required tables {missing_tables}"
                    )

                project_org_col = self._first_column_match(
                    table_columns.get("projects", set()),
                    ("organization_id", "org_id"),
                )
                api_project_col = self._first_column_match(
                    table_columns.get("api_keys", set()),
                    ("project_id",),
                )
                api_org_col = self._first_column_match(
                    table_columns.get("api_keys", set()),
                    ("organization_id", "org_id"),
                )

                results: list[BindingReconciliationResult] = []
                for binding in bindings:
                    issues: list[str] = []
                    try:
                        org_exists = conn.execute(
                            text("SELECT 1 FROM organizations WHERE id = :id LIMIT 1"),
                            {"id": str(binding.langfuse_org_id)},
                        ).fetchone()
                        if not org_exists:
                            issues.append("langfuse_org_missing")

                        project_select_cols = "id"
                        if project_org_col:
                            project_select_cols += f", {project_org_col}"
                        project_row = conn.execute(
                            text(f"SELECT {project_select_cols} FROM projects WHERE id = :id LIMIT 1"),
                            {"id": str(binding.langfuse_project_id)},
                        ).fetchone()
                        if not project_row:
                            issues.append("langfuse_project_missing")
                        elif project_org_col:
                            project_org_id = str(project_row[1]) if project_row[1] is not None else None
                            if project_org_id and project_org_id != str(binding.langfuse_org_id):
                                issues.append("project_org_mismatch")

                        try:
                            public_key = self.decrypt_secret(binding.public_key_encrypted)
                        except Exception:
                            public_key = None
                            issues.append("binding_public_key_decrypt_failed")

                        if public_key:
                            api_select_cols = ["id"]
                            if api_project_col:
                                api_select_cols.append(api_project_col)
                            if api_org_col:
                                api_select_cols.append(api_org_col)
                            api_row = conn.execute(
                                text(
                                    f"SELECT {', '.join(api_select_cols)} "
                                    "FROM api_keys WHERE public_key = :public_key LIMIT 1"
                                ),
                                {"public_key": public_key},
                            ).fetchone()
                            if not api_row:
                                issues.append("langfuse_api_key_missing")
                            else:
                                idx = 1
                                if api_project_col:
                                    api_project_id = str(api_row[idx]) if api_row[idx] is not None else None
                                    idx += 1
                                    if api_project_id and api_project_id != str(binding.langfuse_project_id):
                                        issues.append("api_key_project_mismatch")
                                if api_org_col:
                                    api_org_id = str(api_row[idx]) if api_row[idx] is not None else None
                                    if api_org_id and api_org_id != str(binding.langfuse_org_id):
                                        issues.append("api_key_org_mismatch")

                        results.append(
                            BindingReconciliationResult(
                                binding_id=str(binding.id),
                                status="healthy" if not issues else "drift",
                                issues=issues,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Binding reconciliation failed for binding_id={}", binding.id)
                        results.append(
                            BindingReconciliationResult(
                                binding_id=str(binding.id),
                                status="error",
                                issues=[f"reconcile_error:{exc}"],
                            )
                        )

                return results
        finally:
            engine.dispose()

    @staticmethod
    def _first_column_match(available_columns: set[str], candidates: tuple[str, ...]) -> str | None:
        for candidate in candidates:
            if candidate in available_columns:
                return candidate
        return None


_PROVISIONING_SERVICE: LangfuseProvisioningService | None = None


def get_langfuse_provisioning_service() -> LangfuseProvisioningService:
    global _PROVISIONING_SERVICE
    if _PROVISIONING_SERVICE is None:
        _PROVISIONING_SERVICE = LangfuseProvisioningService()
    return _PROVISIONING_SERVICE
