"""Langfuse client creation, version detection, and binding-scoped client cache."""

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Process-local caches
# ---------------------------------------------------------------------------
_ENV_CLIENT_CACHE: dict[str, Any] = {"fingerprint": None, "client": None}
_BINDING_CLIENT_CACHE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def is_v3_client(client: Any) -> bool:
    """Check if *client* is a Langfuse SDK v3 instance."""
    if getattr(client, "_is_v3", False):
        return True
    api_obj = getattr(client, "api", None)
    return bool(
        hasattr(client, "auth_check")
        or (
            api_obj
            and (
                hasattr(api_obj, "trace")
                or hasattr(api_obj, "traces")
                or hasattr(api_obj, "observations")
                or hasattr(api_obj, "scores")
            )
        )
    )


def _detect_v3(client: Any) -> tuple[bool, str]:
    """Return (is_v3, sdk_version) for a freshly-created Langfuse instance."""
    is_v3 = False
    sdk_version = "unknown"
    try:
        import langfuse
        sdk_version = getattr(langfuse, "__version__", "unknown")
        if sdk_version.startswith("3."):
            is_v3 = True
        if hasattr(client, "api"):
            is_v3 = True
        if hasattr(client, "auth_check"):
            is_v3 = True
    except Exception:
        is_v3 = hasattr(client, "auth_check") or hasattr(client, "api")
    return is_v3, sdk_version


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------

def _create_langfuse_client(
    *,
    secret_key: str,
    public_key: str,
    base_url: str,
    namespace_prefix: str = "scoped",
) -> Any | None:
    """Low-level factory: create a Langfuse client and tag it with version info."""
    try:
        from langfuse import Langfuse
    except ImportError:
        return None
    try:
        client = Langfuse(
            secret_key=secret_key,
            public_key=public_key,
            host=base_url,
        )
        is_v3, sdk_version = _detect_v3(client)
        client._is_v3 = is_v3
        client._sdk_version = sdk_version
        client._trace_cache_namespace = f"{namespace_prefix}:{base_url}:{public_key[-8:]}"
        return client
    except Exception as exc:
        logger.warning("Failed to create Langfuse client: %s", exc)
        return None


def get_langfuse_client() -> Any | None:
    """Return a Langfuse client built from env vars (cached per fingerprint)."""
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")

    if not all([secret_key, public_key, base_url]):
        logger.warning(
            "Langfuse credentials not configured. "
            "Need LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_BASE_URL (or LANGFUSE_HOST)"
        )
        return None

    fingerprint = f"{public_key}:{base_url}:{len(secret_key)}"
    cached = _ENV_CLIENT_CACHE.get("client")
    if cached is not None and _ENV_CLIENT_CACHE.get("fingerprint") == fingerprint:
        if not getattr(cached, "_trace_cache_namespace", None):
            cached._trace_cache_namespace = f"env:{fingerprint}"
        return cached

    # Ensure v3 env var compatibility
    if not os.getenv("LANGFUSE_BASE_URL") and os.getenv("LANGFUSE_HOST"):
        os.environ["LANGFUSE_BASE_URL"] = os.getenv("LANGFUSE_HOST")

    client = _create_langfuse_client(
        secret_key=secret_key,
        public_key=public_key,
        base_url=base_url,
        namespace_prefix="env",
    )
    if client is None:
        _ENV_CLIENT_CACHE["fingerprint"] = None
        _ENV_CLIENT_CACHE["client"] = None
        return None

    # Overwrite namespace to include fingerprint
    client._trace_cache_namespace = f"env:{fingerprint}"

    # Health check
    if client._is_v3:
        try:
            if client.auth_check():
                logger.info("Using Langfuse SDK v3 (%s) - auth_check passed", client._sdk_version)
            else:
                logger.warning("Langfuse v3 (%s) auth_check failed", client._sdk_version)
        except Exception as e:
            logger.debug("v3 auth_check error (continuing anyway): %s", e)
    else:
        logger.info("Using Langfuse SDK v2 (%s)", client._sdk_version)

    _ENV_CLIENT_CACHE["fingerprint"] = fingerprint
    _ENV_CLIENT_CACHE["client"] = client
    return client


def get_langfuse_client_for_binding(binding: Any) -> Any | None:
    """Return a Langfuse client for a DB-managed binding (cached per binding id + updated_at)."""
    from agentcore.services.observability import get_langfuse_provisioning_service

    provisioning_service = get_langfuse_provisioning_service()
    updated_epoch = 0.0
    try:
        if binding.updated_at is not None:
            updated_epoch = float(binding.updated_at.timestamp())
    except Exception:
        pass
    fingerprint = f"{binding.id}:{updated_epoch}"

    cache_entry = _BINDING_CLIENT_CACHE.get(str(binding.id))
    if cache_entry and cache_entry.get("fingerprint") == fingerprint:
        return cache_entry.get("client")

    try:
        public_key = provisioning_service.decrypt_secret(binding.public_key_encrypted)
        secret_key = provisioning_service.decrypt_secret(binding.secret_key_encrypted)
    except Exception as exc:
        logger.warning("Failed decrypting Langfuse binding %s: %s", binding.id, exc)
        return None

    client = _create_langfuse_client(
        secret_key=secret_key,
        public_key=public_key,
        base_url=binding.langfuse_host,
        namespace_prefix="binding",
    )
    if client is None:
        return None
    client._trace_cache_namespace = f"binding:{binding.id}"
    client._agentcore_binding_id = str(binding.id)

    _BINDING_CLIENT_CACHE[str(binding.id)] = {
        "fingerprint": fingerprint,
        "client": client,
    }
    return client
