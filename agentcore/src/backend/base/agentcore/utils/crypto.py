"""Fernet-based encryption for API keys stored in the model registry."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet


def _get_encryption_key() -> str:
    """Get the encryption key from environment or generate a deterministic fallback."""
    key = os.getenv("MODEL_REGISTRY_ENCRYPTION_KEY") or os.getenv("WEBUI_SECRET_KEY")
    if not key:
        key = Fernet.generate_key().decode()
    return key


def _get_fernet(encryption_key: str) -> Fernet:
    key_bytes = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
    return Fernet(key_bytes)


def encrypt_api_key(plain_key: str, encryption_key: str) -> str:
    """Encrypt a plain-text API key and return a URL-safe base64 string."""
    f = _get_fernet(encryption_key)
    return f.encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key: str, encryption_key: str) -> str:
    """Decrypt a previously encrypted API key back to plain text."""
    f = _get_fernet(encryption_key)
    return f.decrypt(encrypted_key.encode()).decode()