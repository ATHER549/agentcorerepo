"""CRUD operations for the MCP server registry."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.registry import (
    McpRegistry,
    McpRegistryCreate,
    McpRegistryRead,
    McpRegistryUpdate,
)
from app.utils.key_vault import (
    KeyVaultConfig,
    KeyVaultSecretStore,
    mcp_env_vars_secret_name,
    mcp_headers_secret_name,
)

logger = logging.getLogger(__name__)

def _build_key_vault_store() -> KeyVaultSecretStore | None:
    settings = get_settings()
    config = KeyVaultConfig(
        vault_url=settings.key_vault_url,
        secret_prefix=settings.key_vault_secret_prefix,
        tenant_id=settings.key_vault_tenant_id,
        client_id=settings.key_vault_client_id,
        client_secret=settings.key_vault_client_secret,
    )
    return KeyVaultSecretStore.from_config(config)


def _require_key_vault_store() -> KeyVaultSecretStore:
    kv = _build_key_vault_store()
    if kv is None:
        msg = "Azure Key Vault is required for MCP registry secrets. Set MCP_SERVICE_KEY_VAULT_URL."
        raise RuntimeError(msg)
    return kv


def _encode_json(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _decode_json(payload: str) -> dict:
    return json.loads(payload)


async def create_server(
    session: AsyncSession,
    data: McpRegistryCreate,
) -> McpRegistryRead:
    """Register a new MCP server."""
    settings = get_settings()
    key_vault = _require_key_vault_store()
    row = McpRegistry(
        server_name=data.server_name,
        description=data.description,
        mode=data.mode,
        url=data.url,
        command=data.command,
        args=data.args,
        is_active=data.is_active,
        created_by=data.created_by,
        # Tenancy / RBAC fields
        deployment_env=getattr(data, "deployment_env", "DEV"),
        status=getattr(data, "status", "disconnected"),
        org_id=data.org_id,
        dept_id=data.dept_id,
        visibility=getattr(data, "visibility", "private"),
        public_scope=data.public_scope,
        public_dept_ids=data.public_dept_ids,
        shared_user_ids=data.shared_user_ids,
        approval_status=getattr(data, "approval_status", "approved"),
        requested_by=data.requested_by,
        request_to=data.request_to,
        created_by_id=data.created_by_id,
    )

    session.add(row)
    await session.flush()

    if data.env_vars:
        env_secret_name = mcp_env_vars_secret_name(settings.key_vault_secret_prefix, row.id)
        await asyncio.to_thread(key_vault.set_secret, env_secret_name, _encode_json(data.env_vars))
        row.env_vars_secret_ref = env_secret_name

    if data.headers:
        headers_secret_name = mcp_headers_secret_name(settings.key_vault_secret_prefix, row.id)
        await asyncio.to_thread(key_vault.set_secret, headers_secret_name, _encode_json(data.headers))
        row.headers_secret_ref = headers_secret_name

    await session.commit()
    await session.refresh(row)
    return McpRegistryRead.from_orm_model(row)


async def get_servers(
    session: AsyncSession,
    *,
    active_only: bool = True,
) -> list[McpRegistryRead]:
    """Return all MCP servers, optionally filtered by active status."""
    stmt = select(McpRegistry)
    if active_only:
        stmt = stmt.where(McpRegistry.is_active.is_(True))
    stmt = stmt.order_by(McpRegistry.server_name)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [McpRegistryRead.from_orm_model(r) for r in rows]


async def get_server(session: AsyncSession, server_id: UUID) -> McpRegistryRead | None:
    """Return a single MCP server by ID."""
    row = await session.get(McpRegistry, server_id)
    if row is None:
        return None
    return McpRegistryRead.from_orm_model(row)


async def get_server_by_name(session: AsyncSession, server_name: str) -> McpRegistryRead | None:
    """Return a single MCP server by name."""
    stmt = select(McpRegistry).where(McpRegistry.server_name == server_name)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is None:
        return None
    return McpRegistryRead.from_orm_model(row)


async def update_server(
    session: AsyncSession,
    server_id: UUID,
    data: McpRegistryUpdate,
) -> McpRegistryRead | None:
    """Update an existing MCP server."""
    settings = get_settings()
    key_vault = _require_key_vault_store()
    row = await session.get(McpRegistry, server_id)
    if row is None:
        return None

    update_fields = data.model_dump(exclude_unset=True)

    # Handle secrets separately
    plain_env_vars = update_fields.pop("env_vars", None)
    if plain_env_vars is not None:
        if plain_env_vars:
            env_secret_name = row.env_vars_secret_ref or mcp_env_vars_secret_name(
                settings.key_vault_secret_prefix, row.id
            )
            await asyncio.to_thread(key_vault.set_secret, env_secret_name, _encode_json(plain_env_vars))
            row.env_vars_secret_ref = env_secret_name
        else:
            row.env_vars_secret_ref = None

    plain_headers = update_fields.pop("headers", None)
    if plain_headers is not None:
        if plain_headers:
            headers_secret_name = row.headers_secret_ref or mcp_headers_secret_name(
                settings.key_vault_secret_prefix, row.id
            )
            await asyncio.to_thread(key_vault.set_secret, headers_secret_name, _encode_json(plain_headers))
            row.headers_secret_ref = headers_secret_name
        else:
            row.headers_secret_ref = None

    for field, value in update_fields.items():
        setattr(row, field, value)

    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return McpRegistryRead.from_orm_model(row)


async def delete_server(session: AsyncSession, server_id: UUID) -> bool:
    """Hard-delete an MCP server. Returns True if the row existed."""
    key_vault = _require_key_vault_store()
    row = await session.get(McpRegistry, server_id)
    if row is None:
        return False
    env_secret_name = row.env_vars_secret_ref
    headers_secret_name = row.headers_secret_ref
    await session.delete(row)
    await session.commit()
    if env_secret_name:
        try:
            await asyncio.to_thread(key_vault.delete_secret, env_secret_name)
        except Exception:
            logger.warning("Failed to delete MCP env secret '%s' for server %s", env_secret_name, server_id)
    if headers_secret_name:
        try:
            await asyncio.to_thread(key_vault.delete_secret, headers_secret_name)
        except Exception:
            logger.warning("Failed to delete MCP headers secret '%s' for server %s", headers_secret_name, server_id)
    return True


async def get_decrypted_config_by_id(
    session: AsyncSession,
    server_id: UUID,
) -> tuple[str, dict] | None:
    """Return (server_name, config_dict) with decrypted secrets, looked up by ID."""
    key_vault = _require_key_vault_store()
    row = await session.get(McpRegistry, server_id)
    if row is None:
        return None

    config: dict = {}

    if row.mode == "sse":
        if row.url:
            config["url"] = row.url
        if row.headers_secret_ref:
            payload = await asyncio.to_thread(key_vault.get_secret, row.headers_secret_ref)
            if not payload:
                raise RuntimeError(f"MCP headers secret '{row.headers_secret_ref}' not found.")
            config["headers"] = _decode_json(payload)
    elif row.mode == "stdio":
        if row.command:
            config["command"] = row.command
        if row.args:
            config["args"] = row.args

    if row.env_vars_secret_ref:
        payload = await asyncio.to_thread(key_vault.get_secret, row.env_vars_secret_ref)
        if not payload:
            raise RuntimeError(f"MCP env secret '{row.env_vars_secret_ref}' not found.")
        config["env"] = _decode_json(payload)

    return row.server_name, config


async def get_decrypted_config(
    session: AsyncSession,
    server_name: str,
) -> dict | None:
    """Return the full MCP server config with decrypted secrets."""
    key_vault = _require_key_vault_store()
    stmt = select(McpRegistry).where(McpRegistry.server_name == server_name)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is None:
        return None

    config: dict = {}

    if row.mode == "sse":
        if row.url:
            config["url"] = row.url
        if row.headers_secret_ref:
            payload = await asyncio.to_thread(key_vault.get_secret, row.headers_secret_ref)
            if not payload:
                raise RuntimeError(f"MCP headers secret '{row.headers_secret_ref}' not found.")
            config["headers"] = _decode_json(payload)
    elif row.mode == "stdio":
        if row.command:
            config["command"] = row.command
        if row.args:
            config["args"] = row.args

    # Env vars apply to both modes
    if row.env_vars_secret_ref:
        payload = await asyncio.to_thread(key_vault.get_secret, row.env_vars_secret_ref)
        if not payload:
            raise RuntimeError(f"MCP env secret '{row.env_vars_secret_ref}' not found.")
        config["env"] = _decode_json(payload)

    return config
