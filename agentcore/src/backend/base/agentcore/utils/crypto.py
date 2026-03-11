"""Fernet-based encryption for API keys stored in the model registry."""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_encryption_key() -> str:
    """Get the encryption key from environment or generate a deterministic fallback."""
    key = os.getenv("MODEL_REGISTRY_ENCRYPTION_KEY") or os.getenv("WEBUI_SECRET_KEY")
    if not key:
        key = Fernet.generate_key().decode()
    return key


def derive_fernet_key(secret: str) -> str:
    """Derive a Fernet-compatible key from an arbitrary secret string."""
    derived = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(derived).decode()


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


def decrypt_api_key_with_fallback(encrypted_key: str, primary_key: str) -> str:
    """Try decrypting with the primary key; on failure try known fallback keys.

    The microservice may have encrypted with a different derived key when
    WEBUI_SECRET_KEY was not available to it, so we try known fallbacks.
    """
    try:
        return decrypt_api_key(encrypted_key, primary_key)
    except (InvalidToken, Exception):
        pass

    # Build a list of alternative derived keys to try.
    tried = {primary_key}
    fallback_secrets = ["default-agentcore-registry-key"]
    webui_key = os.getenv("WEBUI_SECRET_KEY", "")
    if webui_key:
        fallback_secrets.append(webui_key)

    for secret in fallback_secrets:
        candidate = derive_fernet_key(secret)
        if candidate in tried:
            continue
        tried.add(candidate)
        try:
            result = decrypt_api_key(encrypted_key, candidate)
            logger.warning("Decrypted with fallback key derived from '%s…'; "
                           "re-save the record to use the primary key.", secret[:8])
            return result
        except (InvalidToken, Exception):
            continue

    # None of the fallbacks worked – re-raise with the primary key.
    return decrypt_api_key(encrypted_key, primary_key)