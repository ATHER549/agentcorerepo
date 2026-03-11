"""Fernet-based encryption utilities."""

from __future__ import annotations

from cryptography.fernet import Fernet


def _get_fernet(encryption_key: str) -> Fernet:
    key_bytes = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
    return Fernet(key_bytes)


def encrypt_api_key(plain_key: str, encryption_key: str) -> str:
    f = _get_fernet(encryption_key)
    return f.encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key: str, encryption_key: str) -> str:
    f = _get_fernet(encryption_key)
    return f.decrypt(encrypted_key.encode()).decode()
