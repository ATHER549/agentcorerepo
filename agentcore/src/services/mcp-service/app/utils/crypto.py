"""Fernet-based encryption for secrets stored in the MCP registry."""

from __future__ import annotations

import json

from cryptography.fernet import Fernet


def _get_fernet(encryption_key: str) -> Fernet:
    key_bytes = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
    return Fernet(key_bytes)


def encrypt_api_key(plain_key: str, encryption_key: str) -> str:
    """Encrypt a plain-text string and return a URL-safe base64 string."""
    f = _get_fernet(encryption_key)
    return f.encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key: str, encryption_key: str) -> str:
    """Decrypt a previously encrypted string back to plain text."""
    f = _get_fernet(encryption_key)
    return f.decrypt(encrypted_key.encode()).decode()


def encrypt_json(data: dict, encryption_key: str) -> str:
    """Encrypt a dict as JSON string."""
    return encrypt_api_key(json.dumps(data), encryption_key)


def decrypt_json(encrypted: str, encryption_key: str) -> dict:
    """Decrypt an encrypted JSON string back to dict."""
    return json.loads(decrypt_api_key(encrypted, encryption_key))
