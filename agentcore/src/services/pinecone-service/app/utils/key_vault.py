"""Azure Key Vault secret client for pinecone-service."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class KeyVaultConfig(BaseModel):
    vault_url: str | None = None
    secret_prefix: str = "agentcore-pinecone"
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None


@dataclass(slots=True)
class KeyVaultSecretStore:
    """Thin wrapper around Azure Key Vault SecretClient."""

    _client: object
    secret_prefix: str

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
        return cls(_client=client, secret_prefix=config.secret_prefix)

    def get_secret(self, name: str) -> str | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._client.get_secret(name).value
        except ResourceNotFoundError:
            return None
