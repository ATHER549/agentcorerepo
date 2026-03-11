"""CRUD operations for the model registry."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.services.database.models.model_registry.model import (
    ModelRegistry,
    ModelRegistryCreate,
    ModelRegistryRead,
    ModelRegistryUpdate,
)
from agentcore.utils.crypto import decrypt_api_key, decrypt_api_key_with_fallback, derive_fernet_key, encrypt_api_key

logger = logging.getLogger(__name__)


def _encryption_key() -> str:
    """Return the primary encryption key from environment."""
    key = os.getenv("MODEL_REGISTRY_ENCRYPTION_KEY", "")
    if not key:
        raw = os.getenv("WEBUI_SECRET_KEY", "default-agentcore-registry-key")
        key = derive_fernet_key(raw)
    return key


async def create_model(
    session: AsyncSession,
    data: ModelRegistryCreate,
) -> ModelRegistryRead:
    """Insert a new model into the registry."""
    enc_key = _encryption_key()
    row = ModelRegistry(
        display_name=data.display_name,
        description=data.description,
        provider=data.provider,
        model_name=data.model_name,
        model_type=data.model_type,
        base_url=data.base_url,
        environment=data.environment,
        source_model_id=getattr(data, "source_model_id", None),
        org_id=getattr(data, "org_id", None),
        dept_id=getattr(data, "dept_id", None),
        public_dept_ids=[str(v) for v in (getattr(data, "public_dept_ids", None) or [])] or None,
        created_by_id=getattr(data, "created_by_id", None),
        visibility_scope=getattr(data, "visibility_scope", "private"),
        approval_status=getattr(data, "approval_status", "approved"),
        requested_by=getattr(data, "requested_by", None),
        request_to=getattr(data, "request_to", None),
        requested_at=getattr(data, "requested_at", None),
        reviewed_at=getattr(data, "reviewed_at", None),
        reviewed_by=getattr(data, "reviewed_by", None),
        review_comments=getattr(data, "review_comments", None),
        review_attachments=getattr(data, "review_attachments", None),
        provider_config=data.provider_config,
        capabilities=data.capabilities,
        default_params=data.default_params,
        is_active=data.is_active,
        created_by=data.created_by,
    )

    if data.api_key and enc_key:
        row.api_key_secret_ref = encrypt_api_key(data.api_key, enc_key)

    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ModelRegistryRead.from_orm_model(row)


async def get_models(
    session: AsyncSession,
    *,
    provider: str | None = None,
    environment: str | None = None,
    model_type: str | None = None,
    active_only: bool = True,
) -> list[ModelRegistryRead]:
    """Return all registry entries, optionally filtered."""
    stmt = select(ModelRegistry)
    if active_only:
        stmt = stmt.where(ModelRegistry.is_active.is_(True))
    if provider:
        stmt = stmt.where(ModelRegistry.provider == provider)
    if environment:
        stmt = stmt.where(ModelRegistry.environment == environment)
    if model_type:
        stmt = stmt.where(ModelRegistry.model_type == model_type)
    stmt = stmt.order_by(ModelRegistry.provider, ModelRegistry.display_name)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [ModelRegistryRead.from_orm_model(r) for r in rows]


async def get_model(session: AsyncSession, model_id: UUID) -> ModelRegistryRead | None:
    """Return a single registry entry by ID."""
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return None
    return ModelRegistryRead.from_orm_model(row)


async def update_model(
    session: AsyncSession,
    model_id: UUID,
    data: ModelRegistryUpdate,
) -> ModelRegistryRead | None:
    """Update an existing registry entry."""
    enc_key = _encryption_key()
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return None

    update_fields = data.model_dump(exclude_unset=True)
    if "public_dept_ids" in update_fields:
        update_fields["public_dept_ids"] = [str(v) for v in (update_fields.get("public_dept_ids") or [])] or None

    # Handle API key separately
    plain_key = update_fields.pop("api_key", None)
    if plain_key and enc_key:
        row.api_key_secret_ref = encrypt_api_key(plain_key, enc_key)

    for field, value in update_fields.items():
        setattr(row, field, value)

    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ModelRegistryRead.from_orm_model(row)


async def delete_model(session: AsyncSession, model_id: UUID) -> bool:
    """Hard-delete a registry entry. Returns True if the row existed."""
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


def _is_fernet_token(value: str) -> bool:
    """Heuristic: Fernet tokens are base64-encoded and start with 'gAAAAA'."""
    return value.startswith("gAAAAA")


_kv_store_cache: dict[str, object] = {}


def _try_resolve_key_vault_secret(secret_name: str) -> str | None:
    """Attempt to fetch a secret from Azure Key Vault.

    Tries the model-service Key Vault config (MODEL_SERVICE_KEY_VAULT_URL) first,
    then falls back to the backend core config (AGENTCORE_KEY_VAULT_URL).

    Returns the secret value, or None if Key Vault is not configured or the
    secret cannot be retrieved.
    """
    from agentcore.services.settings.key_vault import KeyVaultConfig, KeyVaultSecretStore

    # Try model-service KV config first, then backend core KV config
    configs = [
        {
            "vault_url": os.getenv("MODEL_SERVICE_KEY_VAULT_URL", ""),
            "prefix": os.getenv("MODEL_SERVICE_KEY_VAULT_SECRET_PREFIX", "agentcore"),
            "tenant_id": os.getenv("MODEL_SERVICE_KEY_VAULT_TENANT_ID", ""),
            "client_id": os.getenv("MODEL_SERVICE_KEY_VAULT_CLIENT_ID", ""),
            "client_secret": os.getenv("MODEL_SERVICE_KEY_VAULT_CLIENT_SECRET", ""),
        },
        {
            "vault_url": os.getenv("AGENTCORE_KEY_VAULT_URL", ""),
            "prefix": os.getenv("AGENTCORE_KEY_VAULT_SECRET_PREFIX", "agentcore"),
            "tenant_id": os.getenv("AGENTCORE_KEY_VAULT_TENANT_ID", ""),
            "client_id": os.getenv("AGENTCORE_KEY_VAULT_CLIENT_ID", ""),
            "client_secret": os.getenv("AGENTCORE_KEY_VAULT_CLIENT_SECRET", ""),
        },
    ]

    for cfg in configs:
        vault_url = (cfg["vault_url"] or "").strip()
        if not vault_url:
            continue
        cache_key = vault_url
        if cache_key not in _kv_store_cache:
            try:
                store = KeyVaultSecretStore.from_config(KeyVaultConfig(
                    vault_url=vault_url,
                    secret_prefix=cfg["prefix"],
                    tenant_id=cfg["tenant_id"] or None,
                    client_id=cfg["client_id"] or None,
                    client_secret=cfg["client_secret"] or None,
                ))
                _kv_store_cache[cache_key] = store
            except Exception:
                _kv_store_cache[cache_key] = None
        store = _kv_store_cache[cache_key]
        if store is None:
            continue
        try:
            value = store.get_secret(secret_name)
            if value:
                return value
        except Exception as e:
            logger.debug("Key Vault lookup failed for '%s' at %s: %s", secret_name, vault_url, e)
            continue

    return None


async def get_decrypted_config(
    session: AsyncSession,
    model_id: UUID,
) -> dict | None:
    """Return the full config with decrypted API key.  Internal use only (components)."""
    enc_key = _encryption_key()
    row = await session.get(ModelRegistry, model_id)
    if row is None:
        return None

    config: dict = {
        "provider": row.provider,
        "model_name": row.model_name,
        "base_url": row.base_url,
        "environment": row.environment,
        "provider_config": row.provider_config or {},
        "capabilities": row.capabilities or {},
        "default_params": row.default_params or {},
    }

    secret_ref = row.api_key_secret_ref
    if secret_ref:
        if _is_fernet_token(secret_ref):
            # Locally encrypted with Fernet
            config["api_key"] = decrypt_api_key_with_fallback(secret_ref, enc_key)
        else:
            # Likely an Azure Key Vault secret name — try to resolve it
            resolved = _try_resolve_key_vault_secret(secret_ref)
            if resolved:
                config["api_key"] = resolved
            else:
                # Fall back to the model-service API which has Key Vault credentials
                svc_config = await _fetch_config_from_model_service(model_id)
                if svc_config and svc_config.get("api_key"):
                    config["api_key"] = svc_config["api_key"]
                else:
                    logger.warning(
                        "Cannot resolve api_key_secret_ref for model %s: "
                        "value '%s…' is neither a Fernet token nor resolvable via Key Vault or model-service. "
                        "Returning empty api_key.",
                        model_id,
                        secret_ref[:30],
                    )
                    config["api_key"] = ""
    else:
        config["api_key"] = ""

    return config


async def _fetch_config_from_model_service(model_id: UUID) -> dict | None:
    """Try to fetch decrypted config from the model-service microservice."""
    try:
        from agentcore.services.model_service_client import fetch_decrypted_model_config
        return await fetch_decrypted_model_config(str(model_id))
    except Exception as e:
        logger.debug("Model-service config fetch failed for %s: %s", model_id, e)
        return None
