import base64
import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.utils.key_vault import KeyVaultConfig, KeyVaultSecretStore

logger = logging.getLogger(__name__)

_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


def _read_root_env_key(name: str) -> str:
    if not _ROOT_ENV.exists():
        return ""
    try:
        for line in _ROOT_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip().strip("'\"")
    except Exception:
        pass
    return ""


def _derive_encryption_key() -> str:
    key = os.getenv("GRAPH_RAG_SERVICE_ENCRYPTION_KEY", "").strip()
    if key and key not in ("your-secret-key-here", "your-fernet-key-here"):
        return key

    raw = os.getenv("WEBUI_SECRET_KEY", "").strip()
    if not raw:
        raw = _read_root_env_key("WEBUI_SECRET_KEY")
    if not raw:
        raw = "default-agentcore-registry-key"
        logger.warning(
            "No GRAPH_RAG_SERVICE_ENCRYPTION_KEY or WEBUI_SECRET_KEY set — "
            "using default key. Set a proper key for production!"
        )

    derived = hashlib.sha256(raw.encode()).digest()
    return base64.urlsafe_b64encode(derived).decode()


class Settings(BaseSettings):
    api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8004
    log_level: str = "info"
    cors_origins: str = "*"
    database_url: str | None = None
    encryption_key: str = ""
    key_vault_url: str | None = None
    key_vault_secret_prefix: str = "agentcore-graph-rag"
    key_vault_tenant_id: str | None = None
    key_vault_client_id: str | None = None
    key_vault_client_secret: str | None = None
    key_vault_api_key_secret_name: str | None = None
    key_vault_neo4j_password_secret_name: str | None = None
    key_vault_database_url_secret_name: str | None = None

    # Neo4j
    neo4j_uri: str = ""
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # Batch sizes
    ingest_batch_size: int = 100
    embed_batch_size: int = 200

    model_config = SettingsConfigDict(
        env_prefix="GRAPH_RAG_SERVICE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.encryption_key or settings.encryption_key in (
        "your-secret-key-here",
        "your-fernet-key-here",
    ):
        settings.encryption_key = _derive_encryption_key()
    # Resolve required runtime secrets from Azure Key Vault (no fallback to plain .env values).
    if settings.key_vault_url:
        kv_store = KeyVaultSecretStore.from_config(
            KeyVaultConfig(
                vault_url=settings.key_vault_url,
                secret_prefix=settings.key_vault_secret_prefix,
                tenant_id=settings.key_vault_tenant_id,
                client_id=settings.key_vault_client_id,
                client_secret=settings.key_vault_client_secret,
            )
        )

        def _resolve_required_secret(secret_name: str, setting_name: str) -> str:
            if kv_store is None:
                msg = "Azure Key Vault client is not initialized. Check GRAPH_RAG_SERVICE_KEY_VAULT_URL."
                raise RuntimeError(msg)
            secret_value = kv_store.get_secret(secret_name)
            if not secret_value:
                msg = f"Key Vault secret '{secret_name}' for {setting_name} was not found or is empty."
                raise RuntimeError(msg)
            return secret_value

        if not (settings.key_vault_api_key_secret_name or "").strip():
            msg = "GRAPH_RAG_SERVICE_KEY_VAULT_API_KEY_SECRET_NAME is required."
            raise RuntimeError(msg)
        if not (settings.key_vault_neo4j_password_secret_name or "").strip():
            msg = "GRAPH_RAG_SERVICE_KEY_VAULT_NEO4J_PASSWORD_SECRET_NAME is required."
            raise RuntimeError(msg)
        if not (settings.key_vault_database_url_secret_name or "").strip():
            msg = "GRAPH_RAG_SERVICE_KEY_VAULT_DATABASE_URL_SECRET_NAME is required."
            raise RuntimeError(msg)

        settings.api_key = _resolve_required_secret(
            settings.key_vault_api_key_secret_name.strip(),
            "GRAPH_RAG_SERVICE_API_KEY",
        )
        settings.neo4j_password = _resolve_required_secret(
            settings.key_vault_neo4j_password_secret_name.strip(),
            "NEO4J_PASSWORD",
        )
        settings.database_url = _resolve_required_secret(
            settings.key_vault_database_url_secret_name.strip(),
            "GRAPH_RAG_SERVICE_DATABASE_URL",
        )
    return settings
