"""Fernet-based decryption for API keys stored in the model_registry table."""

from __future__ import annotations

from cryptography.fernet import Fernet


def _get_fernet(encryption_key: str) -> Fernet:
    key_bytes = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
    return Fernet(key_bytes)


def decrypt_api_key(encrypted_key: str, encryption_key: str) -> str:
    """Decrypt a previously encrypted API key back to plain text."""
    f = _get_fernet(encryption_key)
    return f.decrypt(encrypted_key.encode()).decode()
