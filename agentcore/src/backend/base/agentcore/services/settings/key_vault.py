"""Azure Key Vault helpers for backend runtime secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import BaseModel


class KeyVaultConfig(BaseModel):
    vault_url: str | None = None
    secret_prefix: str = "agentcore"
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None


@dataclass(slots=True)
class KeyVaultSecretStore:
    """Thin wrapper around Azure Key Vault SecretClient."""

    _client: object

    @classmethod
    def from_config(cls, config: KeyVaultConfig) -> "KeyVaultSecretStore | None":
        if not config.vault_url:
            return None

        from azure.identity import ClientSecretCredential, DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        if config.tenant_id and config.client_id and config.client_secret:
            credential = ClientSecretCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                client_secret=config.client_secret,
            )
        else:
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)

        client = SecretClient(
            vault_url=config.vault_url,
            credential=credential,
            retry_total=5,
            retry_connect=3,
            retry_read=3,
            retry_backoff_factor=0.8,
        )
        return cls(_client=client)

    def get_secret(self, name: str) -> str | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._client.get_secret(name).value
        except ResourceNotFoundError:
            return None


def resolve_backend_secrets_from_key_vault() -> None:
    """Load required backend secrets from Azure Key Vault into environment."""
    vault_url = os.getenv("AGENTCORE_KEY_VAULT_URL", "").strip()
    if not vault_url:
        return

    kv_store = KeyVaultSecretStore.from_config(
        KeyVaultConfig(
            vault_url=vault_url,
            secret_prefix=os.getenv("AGENTCORE_KEY_VAULT_SECRET_PREFIX", "agentcore").strip() or "agentcore",
            tenant_id=os.getenv("AGENTCORE_KEY_VAULT_TENANT_ID", "").strip() or None,
            client_id=os.getenv("AGENTCORE_KEY_VAULT_CLIENT_ID", "").strip() or None,
            client_secret=os.getenv("AGENTCORE_KEY_VAULT_CLIENT_SECRET", "").strip() or None,
        )
    )
    if kv_store is None:
        msg = "Azure Key Vault client is not initialized. Check AGENTCORE_KEY_VAULT_URL."
        raise RuntimeError(msg)

    mappings = {
        "DATABASE_URL": "AGENTCORE_KEY_VAULT_DATABASE_URL_SECRET_NAME",
        "AGENTCORE_SECRET_KEY": "AGENTCORE_KEY_VAULT_SECRET_KEY_SECRET_NAME",
        "AZURE_CLIENT_SECRET": "AGENTCORE_KEY_VAULT_AZURE_CLIENT_SECRET_SECRET_NAME",
        "REDIS_PASSWORD": "AGENTCORE_KEY_VAULT_REDIS_PASSWORD_SECRET_NAME",
        "AZURE_STORAGE_CONNECTION_STRING": "AGENTCORE_KEY_VAULT_AZURE_STORAGE_CONNECTION_STRING_SECRET_NAME",
        "MODEL_SERVICE_API_KEY": "AGENTCORE_KEY_VAULT_MODEL_SERVICE_API_KEY_SECRET_NAME",
        "MCP_SERVICE_API_KEY": "AGENTCORE_KEY_VAULT_MCP_SERVICE_API_KEY_SECRET_NAME",
        "GUARDRAILS_SERVICE_API_KEY": "AGENTCORE_KEY_VAULT_GUARDRAILS_SERVICE_API_KEY_SECRET_NAME",
        "PINECONE_SERVICE_API_KEY": "AGENTCORE_KEY_VAULT_PINECONE_SERVICE_API_KEY_SECRET_NAME",
        "GRAPH_RAG_SERVICE_API_KEY": "AGENTCORE_KEY_VAULT_GRAPH_RAG_SERVICE_API_KEY_SECRET_NAME",
    }

    for env_name, secret_name_env in mappings.items():
        secret_name = (os.getenv(secret_name_env) or "").strip()
        if not secret_name:
            msg = f"{secret_name_env} is required."
            raise RuntimeError(msg)
        secret_value = kv_store.get_secret(secret_name)
        if not secret_value:
            msg = f"Key Vault secret '{secret_name}' for {env_name} was not found or is empty."
            raise RuntimeError(msg)
        os.environ[env_name] = secret_value
