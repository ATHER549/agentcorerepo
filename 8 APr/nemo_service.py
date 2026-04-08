"""NeMo Guardrails execution service.

This module contains the guardrail execution logic that was previously embedded
in the agentcore backend's services/guardrails/nemo_service.py. It has been
adapted to run as a standalone FastAPI microservice that:

  - Reads guardrail configuration from the guardrail_catalogue table
  - Reads model registry config (with decrypted API key) from the model_registry table
  - Builds and caches NeMo LLMRails instances
  - Executes guardrail checks and returns structured results
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import UUID

import yaml
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.guardrail_catalogue import GuardrailCatalogue
from app.models.model_registry import ModelRegistry
from app.utils.crypto import decrypt_api_key
from app.utils.key_vault import KeyVaultConfig, KeyVaultSecretStore


@dataclass(slots=True)
class GuardrailExecutionResult:
    output_text: str
    action: str
    guardrail_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls_count: int = 0
    model: str | None = None
    provider: str | None = None


@dataclass(slots=True)
class _CachedRails:
    cache_key: str
    rails: Any
    config_path: Path


_RAILS_CACHE: dict[str, _CachedRails] = {}
_RAILS_CACHE_LOCK = Lock()
_DEFAULT_RAILS_CO = 'define bot refuse to respond\n  ""\n'


def _to_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except Exception as exc:  # noqa: BLE001
        msg = f"Invalid guardrail id '{value}'. Expected a UUID."
        raise ValueError(msg) from exc


async def _get_guardrail(
    session: AsyncSession,
    guardrail_id: UUID,
    environment: str | None = None,
) -> GuardrailCatalogue:
    """Look up a guardrail by ID.

    When *environment* is ``"prod"``, the *guardrail_id* is treated as a UAT
    source ID and the corresponding frozen prod copy is resolved instead.
    """
    logger.info(
        "NeMo guardrail lookup started: guardrail_id=%s, environment=%s",
        guardrail_id, environment or "uat",
    )

    if environment == "prod":
        # Resolve the prod copy via source_guardrail_id
        stmt = select(GuardrailCatalogue).where(
            GuardrailCatalogue.source_guardrail_id == guardrail_id,
            GuardrailCatalogue.environment == "prod",
        )
        result = await session.execute(stmt)
        row = result.scalars().first()
        if not row:
            msg = (
                f"No production copy found for guardrail {guardrail_id}. "
                "The guardrail may not have been promoted to prod yet."
            )
            logger.warning("NeMo guardrail lookup failed: %s", msg)
            raise ValueError(msg)
    else:
        row = await session.get(GuardrailCatalogue, guardrail_id)

    if not row:
        msg = f"Guardrail {guardrail_id} was not found."
        logger.warning("NeMo guardrail lookup failed: %s", msg)
        raise ValueError(msg)

    if (row.status or "").lower() != "active":
        msg = f"Guardrail {guardrail_id} is not active."
        logger.warning("NeMo guardrail lookup failed: %s", msg)
        raise ValueError(msg)

    logger.info(
        "NeMo guardrail lookup succeeded: "
        "guardrail_id=%s, resolved_id=%s, environment=%s, name=%s, model_registry_id=%s",
        guardrail_id, row.id, row.environment, row.name, row.model_registry_id,
    )
    return row


@lru_cache
def _get_kv_store() -> KeyVaultSecretStore:
    settings = get_settings()
    kv_store = KeyVaultSecretStore.from_config(
        KeyVaultConfig(
            vault_url=settings.key_vault_url,
            secret_prefix=settings.key_vault_secret_prefix,
        )
    )
    if kv_store is None:
        msg = "Azure Key Vault client is not initialized. Check GUARDRAILS_SERVICE_KEY_VAULT_URL."
        raise RuntimeError(msg)
    return kv_store


async def _get_model_registry_config(
    session: AsyncSession,
    guardrail: GuardrailCatalogue,
) -> dict[str, Any] | None:
    model_registry_id = getattr(guardrail, "model_registry_id", None)
    if not model_registry_id:
        logger.warning(
            "NeMo guardrail model registry is missing: "
            f"guardrail_id={guardrail.id}, guardrail_name={guardrail.name}"
        )
        return None

    logger.info(
        "NeMo model registry lookup started: "
        f"guardrail_id={guardrail.id}, model_registry_id={model_registry_id}"
    )
    model_row = await session.get(ModelRegistry, model_registry_id)
    if not model_row:
        msg = f"Model registry entry {model_registry_id} referenced by guardrail {guardrail.id} was not found."
        logger.warning(f"NeMo model registry lookup failed: {msg}")
        raise ValueError(msg)
    if not bool(model_row.is_active):
        msg = f"Model registry entry {model_registry_id} referenced by guardrail {guardrail.id} is inactive."
        logger.warning(f"NeMo model registry lookup failed: {msg}")
        raise ValueError(msg)

    config: dict[str, Any] = {
        "provider": model_row.provider,
        "model_name": model_row.model_name,
        "model_type": model_row.model_type,
        "base_url": model_row.base_url,
        "environment": model_row.environment,
        "provider_config": model_row.provider_config or {},
        "default_params": model_row.default_params or {},
    }

    secret_ref = model_row.api_key_secret_ref
    if secret_ref:
        if secret_ref.startswith("gAAAAA"):
            # Fernet-encrypted token stored by the main backend
            try:
                settings = get_settings()
                config["api_key"] = decrypt_api_key(secret_ref, settings.encryption_key)
            except Exception:
                logger.exception(
                    "NeMo model registry Fernet decryption failed: "
                    f"guardrail_id={guardrail.id}, model_registry_id={model_registry_id}"
                )
                config["api_key"] = ""
        else:
            # Azure Key Vault secret name
            kv_store = _get_kv_store()
            secret_value = kv_store.get_secret(secret_ref)
            if not secret_value:
                logger.warning(
                    "NeMo model registry secret ref not found in Key Vault: "
                    f"guardrail_id={guardrail.id}, model_registry_id={model_registry_id}, "
                    f"secret_ref={secret_ref}"
                )
                config["api_key"] = ""
            else:
                config["api_key"] = secret_value
    else:
        config["api_key"] = ""

    logger.info(
        "NeMo model registry lookup succeeded: "
        f"guardrail_id={guardrail.id}, model_registry_id={model_registry_id}"
    )
    return config


def _extract_first_str(runtime_config: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = runtime_config.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_placeholder_config_text(value: str) -> bool:
    stripped = value.strip()
    return stripped in {".", "..."}


def _normalize_runtime_config(runtime_config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(runtime_config, dict):
        msg = "Guardrail runtimeConfig must be a JSON object."
        logger.warning(f"NeMo runtime config invalid: {msg}")
        raise ValueError(msg)

    config_yml = _extract_first_str(runtime_config, ("config_yml", "configYml", "config.yml"))
    rails_co = _extract_first_str(runtime_config, ("rails_co", "railsCo", "rails.co", "rails_yml", "railsYml", "rails.yml"))
    prompts_yml = _extract_first_str(runtime_config, ("prompts_yml", "promptsYml", "prompts.yml"))
    extra_files = runtime_config.get("files", {})

    if not config_yml:
        msg = "runtimeConfig must include 'config_yml' (or configYml/config.yml)."
        logger.warning(
            "NeMo runtime config invalid: "
            f"{msg} available_keys={sorted(runtime_config.keys())}"
        )
        raise ValueError(msg)
    if _is_placeholder_config_text(config_yml):
        msg = "runtimeConfig 'config_yml' cannot be a placeholder value ('.' or '...')."
        logger.warning(f"NeMo runtime config invalid: {msg}")
        raise ValueError(msg)
    if rails_co and _is_placeholder_config_text(rails_co):
        rails_co = None
    if prompts_yml and _is_placeholder_config_text(prompts_yml):
        prompts_yml = None
    if extra_files is None:
        extra_files = {}
    if not isinstance(extra_files, dict):
        msg = "runtimeConfig 'files' must be an object of {relativePath: content}."
        logger.warning(f"NeMo runtime config invalid: {msg}")
        raise ValueError(msg)

    if not rails_co:
        rails_co = _DEFAULT_RAILS_CO
        logger.info("NeMo runtime config missing rails_co; using default rails template.")

    logger.info(
        "NeMo runtime config normalized: "
        f"has_prompts={bool(prompts_yml and prompts_yml.strip())}, files_count={len(extra_files)}"
    )
    return {
        "config_yml": config_yml,
        "rails_co": rails_co,
        "prompts_yml": prompts_yml,
        "files": extra_files,
    }


def is_nemo_runtime_config_ready(
    runtime_config: dict[str, Any] | None,
    model_registry_id: UUID | str | None = None,
) -> bool:
    try:
        _normalize_runtime_config(runtime_config)
    except Exception:  # noqa: BLE001
        return False
    return bool(model_registry_id)


# Cache for provider to engine mapping
_PROVIDER_ENGINE_MAPPING = {
    "openai": "openai",
    "azure": "azure_openai",
    "anthropic": "anthropic",
    "google": "google_genai",
    "groq": "groq",
    "openai_compatible": "openai",
}


def _coerce_temperature(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _normalize_provider_for_model_constraints(provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    if normalized == "azure_openai":
        return "azure"
    return normalized


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:  # noqa: BLE001
        return None
    return parsed if parsed > 0 else None


def _is_openai_reasoning_family(provider: str | None, model_name: str | None) -> bool:
    provider_normalized = _normalize_provider_for_model_constraints(provider)
    model_normalized = (model_name or "").strip().lower()
    if provider_normalized not in {"openai", "azure", "openai_compatible"}:
        return False
    return (
        model_normalized.startswith("o1")
        or model_normalized.startswith("o3")
        or model_normalized.startswith("gpt-5")
    )


def _ensure_reasoning_completion_budget(
    provider: str | None,
    model_name: str | None,
    params: dict[str, Any],
) -> int | None:
    if not isinstance(params, dict):
        return None
    if not _is_openai_reasoning_family(provider=provider, model_name=model_name):
        return None
    if "max_completion_tokens" not in params:
        return None

    current_value = _coerce_positive_int(params.get("max_completion_tokens"))
    if current_value is None:
        return None

    minimum_safe_budget = 32
    if current_value < minimum_safe_budget:
        params["max_completion_tokens"] = minimum_safe_budget
        return current_value
    return None


def _should_strip_temperature_for_model(
    provider: str | None,
    model_name: str | None,
    temperature: Any,
) -> bool:
    temp_value = _coerce_temperature(temperature)
    if not _is_openai_reasoning_family(provider=provider, model_name=model_name):
        return False
    if temp_value is None or temp_value == 1.0:
        return False
    return True


def _contains_all(haystack: str, needles: tuple[str, ...]) -> bool:
    return all(token in haystack for token in needles)


def _normalize_error_text(error_text: str) -> str:
    text = (error_text or "").lower()
    for ch in (" ", "_", "-", "`", "'", '"'):
        text = text.replace(ch, "")
    return text


def _build_fallback_llm_params_from_error(
    llm_params: dict[str, Any],
    error_text: str,
) -> tuple[dict[str, Any], list[str]]:
    params = dict(llm_params)
    changes: list[str] = []
    normalized_error = _normalize_error_text(error_text)

    if _contains_all(normalized_error, ("unsupported", "parameter", "maxtokens", "maxcompletiontokens")):
        if "max_tokens" in params:
            value = params.pop("max_tokens")
            params.setdefault("max_completion_tokens", value)
            changes.append("max_tokens->max_completion_tokens")

    if _contains_all(normalized_error, ("unsupported", "parameter", "maxcompletiontokens", "maxtokens")):
        if "max_completion_tokens" in params and "max_tokens" not in params:
            value = params.pop("max_completion_tokens")
            params["max_tokens"] = value
            changes.append("max_completion_tokens->max_tokens")

    if _contains_all(normalized_error, ("unsupported", "parameter", "maxtokens", "maxoutputtokens")):
        if "max_tokens" in params:
            value = params.pop("max_tokens")
            params.setdefault("max_output_tokens", value)
            changes.append("max_tokens->max_output_tokens")

    if _contains_all(normalized_error, ("unsupported", "parameter", "maxoutputtokens", "maxtokens")):
        if "max_output_tokens" in params and "max_tokens" not in params:
            value = params.pop("max_output_tokens")
            params["max_tokens"] = value
            changes.append("max_output_tokens->max_tokens")

    if _contains_all(normalized_error, ("unsupported", "parameter", "streamusage")) and "stream_usage" in params:
        params.pop("stream_usage", None)
        changes.append("removed:stream_usage")

    if (
        _contains_all(normalized_error, ("unsupported", "parameter", "temperature"))
        or _contains_all(normalized_error, ("unsupported", "value", "temperature"))
    ) and "temperature" in params:
        params.pop("temperature", None)
        changes.append("removed:temperature")

    return params, changes


_UNSET: Any = object()


def _rebuild_llm_with_fallback_from_error(llm: Any, error_text: str) -> tuple[Any, list[str]]:
    normalized_error = _normalize_error_text(error_text)

    source_key: str | None = None
    target_key: str | None = None
    if _contains_all(normalized_error, ("unsupported", "parameter", "maxtokens", "maxcompletiontokens")):
        source_key, target_key = "max_tokens", "max_completion_tokens"
    elif _contains_all(normalized_error, ("unsupported", "parameter", "maxtokens", "maxoutputtokens")):
        source_key, target_key = "max_tokens", "max_output_tokens"

    if not source_key or not target_key:
        is_temp_error = (
            _contains_all(normalized_error, ("unsupported", "parameter", "temperature"))
            or _contains_all(normalized_error, ("unsupported", "value", "temperature"))
        )
        if is_temp_error and hasattr(llm, "model_copy"):
            try:
                rebuilt = llm.model_copy(update={"temperature": None})
                return rebuilt, ["llm:temperature->None"]
            except Exception:  # noqa: BLE001
                pass
        return llm, []
    if not hasattr(llm, "model_copy"):
        return llm, []

    changes: list[str] = []
    update_dict: dict[str, Any] = {}
    token_value: Any = None

    top_val = getattr(llm, source_key, _UNSET)
    if top_val is not _UNSET and top_val is not None:
        token_value = top_val
        update_dict[source_key] = None
        changes.append(f"llm:{source_key}->None")

    existing_mkwargs: dict[str, Any] = dict(getattr(llm, "model_kwargs", None) or {})
    if source_key in existing_mkwargs and existing_mkwargs[source_key] is not None:
        mk_val = existing_mkwargs.pop(source_key)
        if token_value is None:
            token_value = mk_val
        update_dict["model_kwargs"] = existing_mkwargs
        changes.append(f"llm:model_kwargs.{source_key}->removed")

    if not changes:
        return llm, []

    if token_value is not None:
        model_fields = getattr(llm, "model_fields", {})
        if target_key in model_fields:
            update_dict[target_key] = token_value
        else:
            mk = dict(update_dict.get("model_kwargs", existing_mkwargs) or {})
            mk[target_key] = token_value
            update_dict["model_kwargs"] = mk
        changes.append(f"llm:{source_key}->{target_key}")

    try:
        rebuilt_llm = llm.model_copy(update=update_dict)
    except Exception:  # noqa: BLE001
        return llm, []

    return rebuilt_llm, changes


def _map_registry_provider_to_nemo_engine(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    engine = _PROVIDER_ENGINE_MAPPING.get(normalized)
    if not engine:
        msg = f"Unsupported model registry provider for NeMo guardrails: {provider}"
        logger.warning(f"NeMo model config invalid: {msg}")
        raise ValueError(msg)
    return engine


def _build_model_parameters(model_config: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    provider = str(model_config.get("provider", "")).strip().lower()
    model_name = str(model_config.get("model_name", "")).strip()
    base_url = (model_config.get("base_url") or "").strip()
    api_key = (model_config.get("api_key") or "").strip()
    provider_config = model_config.get("provider_config") or {}
    default_params = model_config.get("default_params") or {}

    if not provider:
        logger.warning("NeMo model config invalid: provider is missing.")
        raise ValueError("Model registry provider is missing.")
    if not model_name:
        logger.warning("NeMo model config invalid: model_name is missing.")
        raise ValueError("Model registry model_name is missing.")

    engine = _map_registry_provider_to_nemo_engine(provider)
    params: dict[str, Any] = {}

    if provider == "openai":
        if api_key:
            params["openai_api_key"] = api_key
        if base_url:
            params["openai_api_base"] = base_url
    elif provider == "azure":
        if api_key:
            params["openai_api_key"] = api_key
        if base_url:
            params["azure_endpoint"] = base_url
        deployment_name = provider_config.get("azure_deployment") or model_name
        params["deployment_name"] = deployment_name
        api_version = provider_config.get("api_version") or provider_config.get("openai_api_version")
        if api_version:
            params["openai_api_version"] = api_version
    elif provider == "anthropic":
        if api_key:
            params["anthropic_api_key"] = api_key
    elif provider == "google":
        if api_key:
            params["google_api_key"] = api_key
        if base_url:
            params["base_url"] = base_url
    elif provider == "groq":
        if api_key:
            params["groq_api_key"] = api_key
        if base_url:
            params["groq_api_base"] = base_url
    elif provider == "openai_compatible":
        if api_key:
            params["openai_api_key"] = api_key
        if base_url:
            params["openai_api_base"] = base_url
        custom_headers = provider_config.get("custom_headers")
        if isinstance(custom_headers, dict) and custom_headers:
            params["default_headers"] = custom_headers

    if isinstance(default_params, dict):
        params.update({
            k: v for k, v in default_params.items()
            if k not in {
                "model", "model_name", "engine", "api_key", "base_url",
                "openai_api_key", "anthropic_api_key", "google_api_key", "groq_api_key",
                "openai_api_base", "groq_api_base", "azure_endpoint",
                "deployment_name", "azure_deployment", "openai_api_version", "api_version",
            }
        })

    logger.info(
        "NeMo model parameters built: "
        f"provider={provider}, engine={engine}, model={model_name}, has_base_url={bool(base_url)}, "
        f"final_params_keys={sorted(params.keys())}"
    )
    return engine, model_name, params


def _build_effective_runtime_config(
    runtime_config: dict[str, Any],
    model_config: dict[str, Any] | None,
) -> dict[str, Any]:
    if not model_config:
        logger.warning("NeMo effective runtime config uses raw runtimeConfig because model config is missing.")
        return runtime_config

    parsed = yaml.safe_load(runtime_config["config_yml"]) or {}
    if not isinstance(parsed, dict):
        raise ValueError("runtimeConfig.config_yml must parse to a YAML mapping.")

    engine, model_name, params = _build_model_parameters(model_config)
    model_block: dict[str, Any] = {
        "type": "main",
        "engine": engine,
        "model": model_name,
    }
    if params:
        model_block["parameters"] = params

    existing_models = parsed.get("models")
    preserved_models: list[dict[str, Any]] = []
    if isinstance(existing_models, list):
        for item in existing_models:
            if not isinstance(item, dict):
                continue
            model_type = str(item.get("type", "")).strip().lower()
            if model_type != "main":
                preserved_models.append(item)

    parsed["models"] = [model_block, *preserved_models]

    # Always use en_core_web_sm to keep Docker image small.
    parsed.setdefault("lowest_nlu", {})
    if isinstance(parsed["lowest_nlu"], dict):
        parsed["lowest_nlu"]["spacy_model"] = "en_core_web_sm"

    effective = dict(runtime_config)
    effective["config_yml"] = yaml.safe_dump(parsed, sort_keys=False)
    logger.info(
        "NeMo effective runtime config built: "
        f"engine={engine}, model={model_name}, model_parameters_keys={sorted(params.keys())}, "
        f"preserved_models={len(preserved_models)}"
    )
    return effective


def _write_safe_file(base_dir: Path, relative_path: str, content: str) -> None:
    """Write file safely with path traversal protection."""
    if not relative_path or relative_path.strip() in {".", ".."}:
        msg = f"Invalid runtimeConfig file path: '{relative_path}'"
        raise ValueError(msg)

    if ".." in relative_path or relative_path.startswith("/"):
        msg = f"Invalid runtimeConfig file path (path traversal detected): '{relative_path}'"
        raise ValueError(msg)

    base_resolved = base_dir.resolve()
    destination = (base_dir / relative_path).resolve()
    if base_resolved not in destination.parents and destination != base_resolved:
        msg = f"Invalid runtimeConfig file path outside config directory: '{relative_path}'"
        raise ValueError(msg)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def _materialize_config(runtime_config: dict[str, Any]) -> Path:
    config_dir = Path(tempfile.mkdtemp(prefix="guardrails_svc_nemo_"))
    logger.info(f"NeMo runtime config materialization started: config_dir={config_dir}")

    _write_safe_file(config_dir, "config.yml", runtime_config["config_yml"])
    _write_safe_file(config_dir, "rails.co", runtime_config["rails_co"])

    prompts_yml = runtime_config.get("prompts_yml")
    if isinstance(prompts_yml, str) and prompts_yml.strip():
        _write_safe_file(config_dir, "prompts.yml", prompts_yml)

    for relative_path, content in runtime_config.get("files", {}).items():
        if not isinstance(relative_path, str) or not isinstance(content, str):
            msg = "runtimeConfig 'files' entries must be string path -> string content."
            logger.warning(f"NeMo runtime config invalid: {msg}")
            raise ValueError(msg)
        _write_safe_file(config_dir, relative_path, content)

    logger.info(
        "NeMo runtime config materialization completed: "
        f"config_dir={config_dir}, files_count={len(runtime_config.get('files', {}))}"
    )
    return config_dir


def _build_rails_from_config_path(config_dir: Path) -> Any:
    try:
        from nemoguardrails import LLMRails, RailsConfig
        from nemoguardrails.actions.llm import utils as llm_utils
        from nemoguardrails.library.content_safety import actions as content_safety_actions
        from nemoguardrails.library.self_check.input_check import actions as self_check_input_actions
        from nemoguardrails.library.self_check.output_check import actions as self_check_output_actions
        from nemoguardrails.library.topic_safety import actions as topic_safety_actions
    except ImportError as exc:
        msg = "nemoguardrails is not installed. Install it before enabling the NeMo guardrail component."
        logger.exception(msg)
        raise RuntimeError(msg) from exc

    original_llm_call = llm_utils.llm_call
    if not getattr(original_llm_call, "_agentcore_compat_patched", False):

        async def _compat_llm_call(  # type: ignore[override]
            llm: Any,
            prompt: str | list[dict[str, Any]],
            model_name: str | None = None,
            model_provider: str | None = None,
            stop: list[str] | None = None,
            custom_callback_handlers: Any = None,
            llm_params: dict[str, Any] | None = None,
        ) -> str:
            params = dict(llm_params) if isinstance(llm_params, dict) else llm_params

            provider = (llm_utils.get_llm_provider(llm) or "").lower()
            resolved_model_name = (
                model_name
                or getattr(llm, "model", None)
                or getattr(llm, "model_name", None)
                or getattr(llm, "deployment_name", None)
                or getattr(llm, "azure_deployment", None)
                or ""
            )

            if isinstance(params, dict):
                if provider in {"google_genai", "google_vertexai", "vertexai"}:
                    if "max_tokens" in params and "max_output_tokens" not in params:
                        params["max_output_tokens"] = params.pop("max_tokens")
                    params.pop("stream_usage", None)
                elif provider in {"groq"}:
                    params.pop("stream_usage", None)
                else:
                    if "max_tokens" in params and "max_completion_tokens" not in params:
                        try:
                            probe = llm.model_copy(update={"max_tokens": 1})
                            probe_defaults = probe._default_params
                            if (
                                isinstance(probe_defaults, dict)
                                and "max_completion_tokens" in probe_defaults
                                and "max_tokens" not in probe_defaults
                            ):
                                params["max_completion_tokens"] = params.pop("max_tokens")
                                logger.info(
                                    "NeMo llm_call adjusted: rewrote max_tokens→max_completion_tokens "
                                    f"(probe: _default_params prefers max_completion_tokens) for "
                                    f"provider={provider}, model={resolved_model_name}"
                                )
                        except Exception:  # noqa: BLE001
                            pass

                if _should_strip_temperature_for_model(
                    provider=provider,
                    model_name=str(resolved_model_name),
                    temperature=params.get("temperature"),
                ):
                    original_temp = params.pop("temperature", None)
                    logger.info(
                        "NeMo llm_call adjusted: removed unsupported temperature from params "
                        f"for provider={provider}, model={resolved_model_name}, "
                        f"original_temperature={original_temp}"
                    )

                previous_budget = _ensure_reasoning_completion_budget(
                    provider=provider,
                    model_name=str(resolved_model_name),
                    params=params,
                )
                if previous_budget is not None:
                    logger.info(
                        "NeMo llm_call adjusted: raised max_completion_tokens for reasoning self-check stability "
                        f"for provider={provider}, model={resolved_model_name}, "
                        f"original_max_completion_tokens={previous_budget}, new_max_completion_tokens=32"
                    )

            try:
                response = await original_llm_call(
                    llm=llm,
                    prompt=prompt,
                    model_name=model_name,
                    model_provider=model_provider,
                    stop=stop,
                    custom_callback_handlers=custom_callback_handlers,
                    llm_params=params,
                )
                logger.debug(
                    "NeMo llm_call succeeded: "
                    f"provider={provider}, model={resolved_model_name}, "
                    f"response_preview={str(response)[:80]!r}"
                )
                return response
            except Exception as exc:  # noqa: BLE001
                error_str = str(exc)
                fallback_params: dict[str, Any] | None = params
                param_changes: list[str] = []
                if isinstance(params, dict):
                    fallback_params, param_changes = _build_fallback_llm_params_from_error(params, error_str)

                fallback_llm, llm_changes = _rebuild_llm_with_fallback_from_error(llm, error_str)
                changes = [*param_changes, *llm_changes]
                if not changes:
                    raise

                logger.warning(
                    "NeMo llm_call retry with fallback params: "
                    f"provider={provider}, model={resolved_model_name}, changes={changes}"
                )

                try:
                    response = await original_llm_call(
                        llm=fallback_llm,
                        prompt=prompt,
                        model_name=model_name,
                        model_provider=model_provider,
                        stop=stop,
                        custom_callback_handlers=custom_callback_handlers,
                        llm_params=fallback_params,
                    )
                    logger.info(
                        "NeMo llm_call retry succeeded: "
                        f"provider={provider}, model={resolved_model_name}, "
                        f"response_preview={str(response)[:80]!r}"
                    )
                    return response
                except Exception as retry_exc:
                    logger.error(
                        "NeMo llm_call retry also failed: "
                        f"provider={provider}, model={resolved_model_name}, "
                        f"original_changes={changes}, retry_error={retry_exc!r}"
                    )
                    raise

        setattr(_compat_llm_call, "_agentcore_compat_patched", True)
        llm_utils.llm_call = _compat_llm_call
        content_safety_actions.llm_call = _compat_llm_call
        self_check_input_actions.llm_call = _compat_llm_call
        self_check_output_actions.llm_call = _compat_llm_call
        topic_safety_actions.llm_call = _compat_llm_call

    rails_config = RailsConfig.from_path(str(config_dir))
    logger.info(f"NeMo rails config loaded from path: config_dir={config_dir}")

    class AgentcoreLLMRails(LLMRails):
        def _prepare_model_kwargs(self, model_config):  # type: ignore[override]
            kwargs = super()._prepare_model_kwargs(model_config)
            provider = str(getattr(model_config, "engine", "")).lower()
            if provider in {"groq", "google_genai", "google_vertexai", "vertexai"}:
                kwargs.pop("stream_usage", None)
            return kwargs

    return AgentcoreLLMRails(rails_config)


def _create_cached_rails(runtime_config: dict[str, Any], cache_key: str) -> _CachedRails:
    config_dir = _materialize_config(runtime_config)
    try:
        rails = _build_rails_from_config_path(config_dir)
    except Exception:  # noqa: BLE001
        shutil.rmtree(config_dir, ignore_errors=True)
        raise
    return _CachedRails(cache_key=cache_key, rails=rails, config_path=config_dir)


def _cleanup_cached_entry(entry: _CachedRails | None) -> None:
    if entry is None:
        return
    shutil.rmtree(entry.config_path, ignore_errors=True)


def _build_cache_key(runtime_config: dict[str, Any], updated_at: datetime | None) -> str:
    updated_at_iso = (updated_at or datetime.now(timezone.utc)).isoformat()
    payload = {"runtime_config": runtime_config, "updated_at": updated_at_iso}
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _get_or_create_rails(
    guardrail_id: UUID,
    runtime_config: dict[str, Any],
    updated_at: datetime | None,
) -> Any:
    cache_key = _build_cache_key(runtime_config, updated_at)
    cache_id = str(guardrail_id)

    with _RAILS_CACHE_LOCK:
        cached = _RAILS_CACHE.get(cache_id)
        if cached and cached.cache_key == cache_key:
            logger.info(
                "NeMo rails cache hit: "
                f"guardrail_id={guardrail_id}, cache_key_prefix={cache_key[:8]}"
            )
            return cached.rails

    logger.info(
        "NeMo rails cache miss: "
        f"guardrail_id={guardrail_id}, cache_key_prefix={cache_key[:8]}"
    )
    new_entry = await asyncio.to_thread(_create_cached_rails, runtime_config, cache_key)

    with _RAILS_CACHE_LOCK:
        cached = _RAILS_CACHE.get(cache_id)
        if cached and cached.cache_key == cache_key:
            logger.info(
                "NeMo rails cache race resolved with existing entry: "
                f"guardrail_id={guardrail_id}, cache_key_prefix={cache_key[:8]}"
            )
            asyncio.create_task(asyncio.to_thread(_cleanup_cached_entry, new_entry))
            return cached.rails
        old_entry = _RAILS_CACHE.pop(cache_id, None)
        _RAILS_CACHE[cache_id] = new_entry

    if old_entry:
        logger.info(
            "NeMo rails cache entry replaced: "
            f"guardrail_id={guardrail_id}, old_key_prefix={old_entry.cache_key[:8]}, new_key_prefix={cache_key[:8]}"
        )
        asyncio.create_task(asyncio.to_thread(_cleanup_cached_entry, old_entry))
    else:
        logger.info(
            "NeMo rails cache entry created: "
            f"guardrail_id={guardrail_id}, cache_key_prefix={cache_key[:8]}"
        )
    return new_entry.rails


def _extract_generated_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        for key in ("content", "text", "response", "output"):
            value = result.get(key)
            if isinstance(value, str):
                return value
        response_list = result.get("response")
        if isinstance(response_list, list) and response_list:
            for item in response_list:
                if isinstance(item, dict):
                    content = item.get("content")
                    if isinstance(content, str):
                        return content
        return str(result)

    response = getattr(result, "response", None)
    if isinstance(response, str):
        return response
    if isinstance(response, list) and response:
        for item in response:
            if isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, str):
                    return content

    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content:
        chunks: list[str] = []
        for chunk in content:
            if isinstance(chunk, str):
                chunks.append(chunk)
            elif isinstance(chunk, dict):
                value = chunk.get("text") or chunk.get("content")
                if isinstance(value, str):
                    chunks.append(value)
        if chunks:
            return " ".join(chunks)

    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text

    return str(result)


def _extract_activated_rails(result: Any) -> list[dict[str, Any]]:
    log_obj = None
    if isinstance(result, dict):
        log_obj = result.get("log")
    else:
        log_obj = getattr(result, "log", None)

    if not log_obj:
        return []

    if isinstance(log_obj, dict):
        activated = log_obj.get("activated_rails") or []
    else:
        activated = getattr(log_obj, "activated_rails", None) or []

    normalized: list[dict[str, Any]] = []
    for rail in activated:
        if isinstance(rail, dict):
            rail_type = str(rail.get("type") or "")
            rail_name = str(rail.get("name") or "")
            stop = bool(rail.get("stop"))
            decisions = rail.get("decisions") or []
        else:
            rail_type = str(getattr(rail, "type", "") or "")
            rail_name = str(getattr(rail, "name", "") or "")
            stop = bool(getattr(rail, "stop", False))
            decisions = getattr(rail, "decisions", None) or []
        normalized.append(
            {
                "type": rail_type.lower(),
                "name": rail_name,
                "stop": stop,
                "decisions": [str(item) for item in decisions if isinstance(item, str)],
            }
        )
    return normalized


def _extract_llm_calls(result: Any) -> list[dict[str, Any]]:
    log_obj = None
    if isinstance(result, dict):
        log_obj = result.get("log")
    else:
        log_obj = getattr(result, "log", None)

    if not log_obj:
        return []

    if isinstance(log_obj, dict):
        llm_calls = log_obj.get("llm_calls") or []
    else:
        llm_calls = getattr(log_obj, "llm_calls", None) or []

    normalized: list[dict[str, Any]] = []
    for call in llm_calls:
        if isinstance(call, dict):
            prompt_tokens = call.get("prompt_tokens")
            completion_tokens = call.get("completion_tokens")
            total_tokens = call.get("total_tokens")
            model_name = call.get("llm_model_name")
            provider_name = call.get("llm_provider_name")
            task = call.get("task")
        else:
            prompt_tokens = getattr(call, "prompt_tokens", None)
            completion_tokens = getattr(call, "completion_tokens", None)
            total_tokens = getattr(call, "total_tokens", None)
            model_name = getattr(call, "llm_model_name", None)
            provider_name = getattr(call, "llm_provider_name", None)
            task = getattr(call, "task", None)

        prompt_tokens_int = int(prompt_tokens or 0)
        completion_tokens_int = int(completion_tokens or 0)
        total_tokens_int = int(total_tokens or 0)
        if total_tokens_int == 0 and (prompt_tokens_int or completion_tokens_int):
            total_tokens_int = prompt_tokens_int + completion_tokens_int

        normalized.append(
            {
                "prompt_tokens": prompt_tokens_int,
                "completion_tokens": completion_tokens_int,
                "total_tokens": total_tokens_int,
                "llm_model_name": str(model_name) if model_name else None,
                "llm_provider_name": str(provider_name) if provider_name else None,
                "task": str(task) if task else None,
            }
        )
    return normalized


def _summarize_llm_calls(llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    model = None
    provider = None
    for call in llm_calls:
        input_tokens += int(call.get("prompt_tokens") or 0)
        output_tokens += int(call.get("completion_tokens") or 0)
        total_tokens += int(call.get("total_tokens") or 0)
        if model is None and call.get("llm_model_name"):
            model = call["llm_model_name"]
        if provider is None and call.get("llm_provider_name"):
            provider = call["llm_provider_name"]

    if total_tokens == 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "llm_calls_count": len(llm_calls),
        "model": model,
        "provider": provider,
    }


def _is_input_rail_blocked(activated_rails: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    blocked_names: list[str] = []
    for rail in activated_rails:
        if rail.get("type") != "input":
            continue
        decisions = [str(item).strip().lower() for item in rail.get("decisions", [])]
        explicit_block_decision = any(
            item in {"block", "blocked", "refuse", "refused", "unsafe"}
            for item in decisions
        )
        refusal_hint = any(
            ("refuse" in item) or ("block" in item) or ("unsafe" in item)
            for item in decisions
        )
        if explicit_block_decision or (bool(rail.get("stop")) and refusal_hint):
            blocked_names.append(str(rail.get("name") or "<unnamed>"))
    return bool(blocked_names), blocked_names


def _extract_pii_llm_prompt(runtime_config: dict[str, Any] | None) -> str | None:
    """Extract the pii_llm_mask prompt from prompts_yml. Returns None if not found."""
    if not runtime_config:
        return None

    prompts_yml = runtime_config.get("prompts_yml", "")
    if not isinstance(prompts_yml, str) or not prompts_yml.strip():
        return None

    try:
        parsed = yaml.safe_load(prompts_yml)
        if not isinstance(parsed, dict):
            return None
        for prompt_entry in parsed.get("prompts", []):
            if isinstance(prompt_entry, dict) and prompt_entry.get("task") == "pii_llm_mask":
                content = prompt_entry.get("content", "").strip()
                if content:
                    return content
    except Exception:  # noqa: BLE001
        logger.debug("Failed to parse prompts_yml for pii_llm_mask task")

    return None


def _extract_pii_detection_mode(runtime_config: dict[str, Any] | None) -> str:
    """Extract pii_detection_mode from config_yml. Returns 'presidio', 'llm', or 'hybrid'. Default: 'presidio'."""
    if not runtime_config:
        return "presidio"

    config_yml = runtime_config.get("config_yml", "")
    if not isinstance(config_yml, str) or not config_yml.strip():
        return "presidio"

    try:
        parsed = yaml.safe_load(config_yml)
        if isinstance(parsed, dict):
            mode = str(parsed.get("pii_detection_mode", "presidio")).strip().lower()
            if mode in ("presidio", "llm", "hybrid"):
                return mode
            logger.warning(f"Invalid pii_detection_mode '{mode}', defaulting to 'presidio'")
    except Exception:  # noqa: BLE001
        logger.debug("Failed to parse config_yml for pii_detection_mode")

    return "presidio"


@dataclass(slots=True)
class _LlmPiiResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls_count: int = 0


async def _llm_pii_mask(rails: Any, text: str, prompt_template: str) -> _LlmPiiResult:
    """Use the guardrail's configured LLM to mask PII. Returns masked text and token usage."""
    try:
        prompt = prompt_template.replace("{{ user_input }}", text)
        response = await rails.llm.ainvoke(prompt)
        masked = response.content if hasattr(response, "content") else str(response)
        masked = masked.strip()
        # Sanity check: if LLM returned empty or something wildly different in length, keep original
        if not masked or len(masked) > len(text) * 3:
            logger.warning("LLM PII mask returned suspicious output, keeping presidio result")
            return _LlmPiiResult(text=text)

        # Extract token usage from response metadata
        usage = getattr(response, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else getattr(usage, "input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else getattr(usage, "output_tokens", 0)

        return _LlmPiiResult(
            text=masked,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            llm_calls_count=1,
        )
    except Exception:  # noqa: BLE001
        logger.exception("LLM PII mask failed, keeping previous result")
        return _LlmPiiResult(text=text)


def _detect_rail_types(runtime_config: dict[str, Any] | None) -> tuple[bool, bool]:
    """Detect whether the guardrail config defines input and/or output flows.

    Returns (has_input, has_output).
    """
    if not runtime_config:
        return True, False

    config_yml = runtime_config.get("config_yml", "")
    if not isinstance(config_yml, str) or not config_yml.strip():
        return True, False

    try:
        parsed = yaml.safe_load(config_yml)
        if not isinstance(parsed, dict):
            return True, False
        rails_cfg = parsed.get("rails", {})
        if not isinstance(rails_cfg, dict):
            return True, False

        input_flows = rails_cfg.get("input", {})
        output_flows = rails_cfg.get("output", {})
        has_input = bool(input_flows.get("flows")) if isinstance(input_flows, dict) else False
        has_output = bool(output_flows.get("flows")) if isinstance(output_flows, dict) else False

        # Default to input if neither is found
        if not has_input and not has_output:
            return True, False
        return has_input, has_output
    except Exception:  # noqa: BLE001
        return True, False


def _is_masking_category(category: str | None) -> bool:
    """Return True if the guardrail category indicates PII masking behavior."""
    if not category:
        return False
    normalized = category.strip().lower().replace(" ", "-").replace("_", "-")
    return any(token in normalized for token in ("pii", "mask", "redact", "anonymi"))


def _classify_action(
    input_text: str,
    output_text: str,
    blocked_by_input_rail: bool,
    guardrail_category: str | None = None,
) -> str:
    input_text_norm = (input_text or "").strip()
    output_text_norm = (output_text or "").strip()

    if blocked_by_input_rail:
        if not output_text_norm:
            return "blocked"
        if output_text_norm != input_text_norm:
            # If the category is PII/masking, the rail modified the text rather than blocking it
            if _is_masking_category(guardrail_category):
                return "masked"
            return "blocked"
        logger.warning(
            "NeMo input rail marked as blocked but output matched input; treating as passthrough."
        )
        return "passthrough"

    if not output_text_norm:
        return "passthrough"
    if output_text_norm == input_text_norm:
        return "passthrough"
    if _is_masking_category(guardrail_category):
        return "masked"
    return "rewritten"


async def apply_nemo_guardrail_text(
    input_text: str,
    guardrail_id: str,
    session: AsyncSession,
    environment: str | None = None,
) -> GuardrailExecutionResult:
    """Apply NeMo guardrails to input_text using the guardrail identified by guardrail_id."""
    started_at = perf_counter()
    logger.info(
        "NeMo guardrail execution started: "
        f"guardrail_id={guardrail_id}, input_length={len(input_text or '')}"
    )
    step = "parse_guardrail_id"
    try:
        guardrail_uuid = _to_uuid(guardrail_id)

        step = "lookup_guardrail"
        guardrail = await _get_guardrail(session, guardrail_uuid, environment=environment)

        step = "lookup_model_registry"
        model_config = await _get_model_registry_config(session, guardrail)

        step = "normalize_runtime_config"
        runtime_config = _normalize_runtime_config(guardrail.runtime_config)

        step = "build_effective_runtime_config"
        effective_runtime_config = _build_effective_runtime_config(runtime_config, model_config)

        step = "resolve_cached_rails"
        rails = await _get_or_create_rails(
            guardrail_id=guardrail_uuid,
            runtime_config=effective_runtime_config,
            updated_at=guardrail.updated_at,
        )

        step = "generate"
        has_input, has_output = _detect_rail_types(effective_runtime_config)
        logger.info(
            f"Rail types detected: has_input={has_input}, has_output={has_output}, "
            f"guardrail_id={guardrail_id}"
        )
        options = {
            "rails": {
                "input": has_input,
                "dialog": False,
                "output": has_output,
                "retrieval": False,
                "tool_input": False,
                "tool_output": False,
            },
            "log": {
                "activated_rails": True,
                "llm_calls": True,
            },
        }
        # NeMo runs input rails on "user" messages and output rails on "assistant" messages.
        # For output rails, NeMo needs a user message + assistant message in the conversation.
        if has_output and not has_input:
            messages = [
                {"role": "user", "content": ""},
                {"role": "assistant", "content": input_text},
            ]
        else:
            messages = [{"role": "user", "content": input_text}]
        try:
            generated = rails.generate_async(messages=messages, options=options)
            if asyncio.iscoroutine(generated):
                generated = await generated
        except Exception as exc:  # noqa: BLE001
            if "log` option is not supported for Colang 2.0" not in str(exc):
                raise
            logger.warning(
                "NeMo guardrail retrying without llm log options because configuration is Colang 2.x: "
                f"guardrail_id={guardrail_id}"
            )
            fallback_options = {"rails": options["rails"]}
            generated = rails.generate_async(messages=messages, options=fallback_options)
            if asyncio.iscoroutine(generated):
                generated = await generated

        step = "extract_rails_log"
        activated_rails = _extract_activated_rails(generated)
        blocked_by_input_rail, blocked_rail_names = _is_input_rail_blocked(activated_rails)
        input_rails_count = sum(1 for rail in activated_rails if rail.get("type") == "input")
        output_rails_count = sum(1 for rail in activated_rails if rail.get("type") == "output")
        logger.info(
            "NeMo guardrail rails log summary: "
            f"guardrail_id={guardrail_id}, activated_rails={len(activated_rails)}, "
            f"input_rails={input_rails_count}, output_rails={output_rails_count}, "
            f"blocked_by_input_rail={blocked_by_input_rail}, "
            f"blocked_input_rails={blocked_rail_names}"
        )
        if input_rails_count == 0 and output_rails_count == 0:
            logger.warning(
                "NeMo guardrail executed with zero active rails: "
                f"guardrail_id={guardrail_id}. Check config_yml rails.input/output.flows and prompts_yml task names."
            )

        llm_calls = _extract_llm_calls(generated)
        llm_usage = _summarize_llm_calls(llm_calls)
        # Fallback: if NeMo's log didn't include model/provider names
        # (common with certain NeMo versions or Colang 2.x), use the
        # model registry config which always has the correct values.
        if not llm_usage["model"] and model_config:
            llm_usage["model"] = model_config.get("model_name")
        if not llm_usage["provider"] and model_config:
            llm_usage["provider"] = model_config.get("provider")
        logger.info(
            "NeMo guardrail llm usage summary: "
            f"guardrail_id={guardrail_id}, llm_calls={llm_usage['llm_calls_count']}, "
            f"input_tokens={llm_usage['input_tokens']}, output_tokens={llm_usage['output_tokens']}, "
            f"total_tokens={llm_usage['total_tokens']}, model={llm_usage['model']}, provider={llm_usage['provider']}"
        )

        step = "extract_output"
        output_text = _extract_generated_text(generated)

        # PII masking mode: presidio (default), llm, or hybrid.
        # - presidio: only Presidio/spaCy NER (already ran above via NeMo rails)
        # - llm: only LLM-based masking (ignore Presidio output, run LLM on original input)
        # - hybrid: run LLM on Presidio's output to catch remaining PII
        pii_llm_result: _LlmPiiResult | None = None
        if _is_masking_category(guardrail.category):
            pii_mode = _extract_pii_detection_mode(effective_runtime_config)
            pii_prompt = _extract_pii_llm_prompt(effective_runtime_config)
            presidio_modified = (output_text or "").strip() != (input_text or "").strip()

            if pii_mode == "llm":
                step = "llm_pii_only"
                if pii_prompt:
                    logger.info(
                        f"PII mode=llm, running LLM-only masking: guardrail_id={guardrail_id}"
                    )
                    pii_llm_result = await _llm_pii_mask(rails, input_text, pii_prompt)
                    output_text = pii_llm_result.text
                else:
                    logger.warning(
                        f"PII mode=llm but no pii_llm_mask prompt configured, skipping: guardrail_id={guardrail_id}"
                    )

            elif pii_mode == "hybrid":
                step = "llm_pii_hybrid"
                if pii_prompt:
                    # Run LLM on Presidio's output (or original input if Presidio didn't modify)
                    llm_input = output_text if presidio_modified else input_text
                    logger.info(
                        f"PII mode=hybrid, running LLM after Presidio (presidio_modified={presidio_modified}): "
                        f"guardrail_id={guardrail_id}"
                    )
                    pii_llm_result = await _llm_pii_mask(rails, llm_input, pii_prompt)
                    output_text = pii_llm_result.text
                else:
                    logger.info(
                        f"PII mode=hybrid but no pii_llm_mask prompt configured, using Presidio-only result: "
                        f"guardrail_id={guardrail_id}"
                    )

            else:
                # pii_mode == "presidio" (default) — Presidio already ran, nothing else to do
                logger.info(
                    f"PII mode=presidio, Presidio-only result (modified={presidio_modified}): "
                    f"guardrail_id={guardrail_id}"
                )

        # Merge LLM PII usage into totals
        if pii_llm_result and pii_llm_result.llm_calls_count > 0:
            llm_usage["llm_calls_count"] += pii_llm_result.llm_calls_count
            llm_usage["input_tokens"] += pii_llm_result.input_tokens
            llm_usage["output_tokens"] += pii_llm_result.output_tokens
            llm_usage["total_tokens"] += pii_llm_result.total_tokens
            logger.info(
                f"PII LLM usage: llm_calls=1, input_tokens={pii_llm_result.input_tokens}, "
                f"output_tokens={pii_llm_result.output_tokens}, total_tokens={pii_llm_result.total_tokens}"
            )

        step = "classify_action"
        action = _classify_action(
            input_text=input_text,
            output_text=output_text,
            blocked_by_input_rail=blocked_by_input_rail,
            guardrail_category=guardrail.category,
        )
        elapsed_ms = (perf_counter() - started_at) * 1000
        if action == "passthrough":
            logger.warning(
                "NeMo guardrail returned passthrough output: "
                f"guardrail_id={guardrail_id}, output_length={len(output_text)}, duration_ms={elapsed_ms:.2f}"
            )
        logger.info(
            "NeMo guardrail execution completed: "
            f"guardrail_id={guardrail_id}, action={action}, output_length={len(output_text)}, "
            f"duration_ms={elapsed_ms:.2f}"
        )
        return GuardrailExecutionResult(
            output_text=output_text,
            action=action,
            guardrail_id=guardrail_id,
            input_tokens=llm_usage["input_tokens"],
            output_tokens=llm_usage["output_tokens"],
            total_tokens=llm_usage["total_tokens"],
            llm_calls_count=llm_usage["llm_calls_count"],
            model=llm_usage["model"],
            provider=llm_usage["provider"],
        )
    except Exception:  # noqa: BLE001
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.exception(
            "NeMo guardrail execution failed: "
            f"guardrail_id={guardrail_id}, step={step}, duration_ms={elapsed_ms:.2f}"
        )
        raise


def clear_nemo_guardrails_cache() -> int:
    """Clear all cached NeMo rails instances. Returns number of entries cleared."""
    with _RAILS_CACHE_LOCK:
        entries = list(_RAILS_CACHE.values())
        _RAILS_CACHE.clear()
    logger.info(f"NeMo rails cache cleared: entries={len(entries)}")
    for entry in entries:
        _cleanup_cached_entry(entry)
    return len(entries)


def invalidate_nemo_guardrail_cache(guardrail_id: str | UUID) -> bool:
    """Invalidate cache for a specific guardrail. Returns True if an entry was removed."""
    cache_id = str(guardrail_id)
    with _RAILS_CACHE_LOCK:
        entry = _RAILS_CACHE.pop(cache_id, None)
    if entry:
        logger.info(f"NeMo rails cache invalidated: guardrail_id={cache_id}")
        _cleanup_cached_entry(entry)
        return True
    logger.info(f"NeMo rails cache invalidation skipped (not found): guardrail_id={cache_id}")
    return False
