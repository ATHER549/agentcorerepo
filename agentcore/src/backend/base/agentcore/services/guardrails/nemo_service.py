from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import UUID

from loguru import logger
import yaml

from agentcore.services import model_registry_service
from agentcore.services.database.models.guardrail_catalogue.model import GuardrailCatalogue
from agentcore.services.database.models.model_registry.model import ModelRegistry
from agentcore.services.deps import session_scope


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
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        msg = f"Invalid guardrail id '{value}'. Expected a UUID."
        raise ValueError(msg) from exc


async def _get_guardrail(guardrail_id: UUID) -> GuardrailCatalogue:
    logger.info(f"NeMo guardrail lookup started: guardrail_id={guardrail_id}")
    async with session_scope() as session:
        row = await session.get(GuardrailCatalogue, guardrail_id)

    if not row:
        msg = f"Guardrail {guardrail_id} was not found."
        logger.warning(f"NeMo guardrail lookup failed: {msg}")
        raise ValueError(msg)

    if (row.status or "").lower() != "active":
        msg = f"Guardrail {guardrail_id} is not active."
        logger.warning(f"NeMo guardrail lookup failed: {msg}")
        raise ValueError(msg)

    logger.info(
        "NeMo guardrail lookup succeeded: "
        f"guardrail_id={guardrail_id}, name={row.name}, model_registry_id={row.model_registry_id}"
    )
    return row


async def _get_model_registry_config(guardrail: GuardrailCatalogue) -> dict[str, Any] | None:
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
    async with session_scope() as session:
        model_row = await session.get(ModelRegistry, model_registry_id)
        if not model_row:
            msg = f"Model registry entry {model_registry_id} referenced by guardrail {guardrail.id} was not found."
            logger.warning(f"NeMo model registry lookup failed: {msg}")
            raise ValueError(msg)
        if not bool(model_row.is_active):
            msg = f"Model registry entry {model_registry_id} referenced by guardrail {guardrail.id} is inactive."
            logger.warning(f"NeMo model registry lookup failed: {msg}")
            raise ValueError(msg)
        config = await model_registry_service.get_decrypted_config(session, model_registry_id)

    if not config:
        msg = f"Model registry entry {model_registry_id} referenced by guardrail {guardrail.id} could not be loaded."
        logger.warning(f"NeMo model registry lookup failed: {msg}")
        raise ValueError(msg)
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
    rails_co = _extract_first_str(runtime_config, ("rails_co", "railsCo", "rails.co"))
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


def _map_registry_provider_to_nemo_engine(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    mapping = {
        "openai": "openai",
        "azure": "azure_openai",
        "anthropic": "anthropic",
        "google": "google_genai",
        "groq": "groq",
        "openai_compatible": "openai",
    }
    engine = mapping.get(normalized)
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
        params.update({k: v for k, v in default_params.items() if k not in {"model", "model_name", "engine"}})

    logger.info(
        "NeMo model parameters built: "
        f"provider={provider}, engine={engine}, model={model_name}, has_base_url={bool(base_url)}, "
        f"default_params_count={len(default_params) if isinstance(default_params, dict) else 0}"
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

    # NeMo topic/content safety actions resolve model instances from `llms`,
    # and `llms` intentionally excludes model type "main". Ensure at least one
    # non-main, non-embedding model exists so safety flows can reference it.
    _EXCLUDED_LLM_TYPES = {"main", "embeddings", "jailbreak_detection"}
    has_usable_safety_model = any(
        str(item.get("type", "")).strip().lower() not in _EXCLUDED_LLM_TYPES
        for item in preserved_models
        if isinstance(item, dict)
    )
    if not has_usable_safety_model:
        safety_model_block = {
            "type": "agentcore_safety",
            "engine": engine,
            "model": model_name,
        }
        if params:
            safety_model_block["parameters"] = dict(params)
        preserved_models.insert(0, safety_model_block)

    parsed["models"] = [model_block, *preserved_models]

    effective = dict(runtime_config)
    effective["config_yml"] = yaml.safe_dump(parsed, sort_keys=False)
    logger.info(
        "NeMo effective runtime config built: "
        f"engine={engine}, model={model_name}, model_parameters_keys={sorted(params.keys())}, "
        f"preserved_models={len(preserved_models)}"
    )
    return effective


def _write_safe_file(base_dir: Path, relative_path: str, content: str) -> None:
    if not relative_path or relative_path.strip() in {".", ".."}:
        msg = f"Invalid runtimeConfig file path: '{relative_path}'"
        raise ValueError(msg)

    base_resolved = base_dir.resolve()
    destination = (base_dir / relative_path).resolve()
    if base_resolved not in destination.parents:
        msg = f"Invalid runtimeConfig file path outside config directory: '{relative_path}'"
        raise ValueError(msg)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def _materialize_config(runtime_config: dict[str, Any]) -> Path:
    config_dir = Path(tempfile.mkdtemp(prefix="agentcore_nemo_guardrails_"))
    logger.info(f"NeMo runtime config materialization started: config_dir={config_dir}")

    # NeMo topic/content safety flows require a $model=<type> qualifier that references
    # a named model in config.yml's `models:` list.  Users often omit this qualifier, so
    # we auto-detect the model type and inject it consistently into both config.yml and
    # prompts.yml before writing to disk.
    _SAFETY_FLOW_IDS = frozenset(
        {
            "topic safety check input",
            "topic safety check output",
            "content safety check input",
            "content safety check output",
        }
    )
    _MODEL_QUALIFIER_TASKS = frozenset(
        {
            "topic_safety_check_input",
            "topic_safety_check_output",
            "content_safety_check_input",
            "content_safety_check_output",
        }
    )

    # --- Step 1: patch config.yml flows ---
    config_yml_str = runtime_config["config_yml"]
    _resolved_safety_model: str = "main"  # fallback; updated if we can parse config
    try:
        _config_parsed = yaml.safe_load(config_yml_str)
        if isinstance(_config_parsed, dict):
            # Determine which model type to use for safety flows.
            # Prefer a dedicated non-main LLM type (especially agentcore_safety).
            _models_list = _config_parsed.get("models") or []
            _safety_model_type = "main"
            if isinstance(_models_list, list):
                _preferred_type = None
                for _m in _models_list:
                    if isinstance(_m, dict):
                        _t = (_m.get("type") or "").strip()
                        _t_lower = _t.lower()
                        if _t_lower == "agentcore_safety":
                            _preferred_type = _t
                            break
                        if _t and _t_lower not in {"main", "embeddings", "jailbreak_detection"}:
                            _preferred_type = _preferred_type or _t
                if _preferred_type:
                    _safety_model_type = _preferred_type
            _resolved_safety_model = _safety_model_type

            # Inject $model=<type> into any safety flow that is missing the qualifier.
            _rails = _config_parsed.get("rails") or {}
            _config_changed = False
            for _section in ("input", "output"):
                _sect = _rails.get(_section) or {}
                if not isinstance(_sect, dict):
                    continue
                _flows = _sect.get("flows") or []
                if not isinstance(_flows, list):
                    continue
                for _i, _flow in enumerate(_flows):
                    if not isinstance(_flow, str):
                        continue
                    _base_flow = _flow.split("$model=")[0].strip()
                    if _base_flow in _SAFETY_FLOW_IDS and "$model=" not in _flow:
                        _flows[_i] = f"{_base_flow} $model={_safety_model_type}"
                        _config_changed = True

            if _config_changed:
                config_yml_str = yaml.dump(_config_parsed, default_flow_style=False, allow_unicode=True)
                logger.info(
                    f"NeMo config_yml: auto-injected '$model={_safety_model_type}' "
                    "into topic/content safety flows for NeMo compatibility."
                )
    except Exception:  # noqa: BLE001
        pass  # Let NeMo surface its own parse error with better context

    _write_safe_file(config_dir, "config.yml", config_yml_str)
    _write_safe_file(config_dir, "rails.co", runtime_config["rails_co"])

    # --- Step 2: patch prompts.yml ---
    prompts_yml = runtime_config.get("prompts_yml")
    if isinstance(prompts_yml, str) and prompts_yml.strip():
        try:
            _parsed_prompts = yaml.safe_load(prompts_yml)
            # Wrap bare list → {"prompts": [...]}
            if isinstance(_parsed_prompts, list):
                _parsed_prompts = {"prompts": _parsed_prompts}
                logger.info(
                    "NeMo prompts_yml was a bare YAML list; "
                    "auto-wrapped under 'prompts:' key for NeMo compatibility."
                )
            # Append " $model=<type>" to topic/content safety task names that are
            # missing the model qualifier, using the same type resolved from config.yml.
            if isinstance(_parsed_prompts, dict):
                _prompt_list = _parsed_prompts.get("prompts")
                if isinstance(_prompt_list, list):
                    _prompts_changed = False
                    for _p in _prompt_list:
                        if isinstance(_p, dict):
                            _task = _p.get("task", "")
                            _base_task = _task.split(" $model=")[0].strip()
                            if _base_task in _MODEL_QUALIFIER_TASKS and "$model=" not in _task:
                                _p["task"] = f"{_base_task} $model={_resolved_safety_model}"
                                _prompts_changed = True
                    if _prompts_changed:
                        logger.info(
                            f"NeMo prompts_yml: auto-appended '$model={_resolved_safety_model}' "
                            "to topic/content safety task names for NeMo compatibility."
                        )
                prompts_yml = yaml.dump(_parsed_prompts, default_flow_style=False, allow_unicode=True)
        except Exception:  # noqa: BLE001
            pass  # Let NeMo surface its own parse error with better context
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
    except ImportError as exc:
        msg = "nemoguardrails is not installed. Install it before enabling the NeMo guardrail component."
        logger.exception(msg)
        raise RuntimeError(msg) from exc

    # Compatibility shim:
    # - Gemini expects max_output_tokens instead of max_tokens.
    # - Some providers reject stream_usage.
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

            if isinstance(params, dict):
                provider = (llm_utils.get_llm_provider(llm) or "").lower()
                if provider in {"google_genai", "google_vertexai", "vertexai"}:
                    if "max_tokens" in params and "max_output_tokens" not in params:
                        params["max_output_tokens"] = params.pop("max_tokens")
                    params.pop("stream_usage", None)
                elif provider in {"groq"}:
                    params.pop("stream_usage", None)

            return await original_llm_call(
                llm=llm,
                prompt=prompt,
                model_name=model_name,
                model_provider=model_provider,
                stop=stop,
                custom_callback_handlers=custom_callback_handlers,
                llm_params=params,
            )

        setattr(_compat_llm_call, "_agentcore_compat_patched", True)
        llm_utils.llm_call = _compat_llm_call
        # Some NeMo actions import llm_call directly at module import time.
        content_safety_actions.llm_call = _compat_llm_call
        self_check_input_actions.llm_call = _compat_llm_call
        self_check_output_actions.llm_call = _compat_llm_call

    rails_config = RailsConfig.from_path(str(config_dir))
    logger.info(f"NeMo rails config loaded from path: config_dir={config_dir}")

    # NeMo currently injects stream_usage=True for all providers.
    # Some providers (for example Groq/Google) reject this parameter.
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
            _cleanup_cached_entry(new_entry)
            return cached.rails
        old_entry = _RAILS_CACHE.get(cache_id)
        _RAILS_CACHE[cache_id] = new_entry

    if old_entry:
        logger.info(
            "NeMo rails cache entry replaced: "
            f"guardrail_id={guardrail_id}, old_key_prefix={old_entry.cache_key[:8]}, new_key_prefix={cache_key[:8]}"
        )
    else:
        logger.info(
            "NeMo rails cache entry created: "
            f"guardrail_id={guardrail_id}, cache_key_prefix={cache_key[:8]}"
        )
    _cleanup_cached_entry(old_entry)
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
            if key == "response" and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        content = item.get("content")
                        if isinstance(content, str):
                            return content
                return ""
        return str(result)

    response = getattr(result, "response", None)
    if isinstance(response, str):
        return response
    if isinstance(response, list):
        for item in response:
            if isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, str):
                    return content
        return ""

    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
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
        has_stop_decision = any(item == "stop" for item in decisions)
        if bool(rail.get("stop")) or has_stop_decision:
            blocked_names.append(str(rail.get("name") or "<unnamed>"))
    return bool(blocked_names), blocked_names


def _classify_action(input_text: str, output_text: str, blocked_by_input_rail: bool) -> str:
    if blocked_by_input_rail:
        return "blocked"
    if not output_text.strip():
        return "passthrough"
    if output_text.strip() == input_text.strip():
        return "passthrough"
    return "rewritten"


async def apply_nemo_guardrail_text(input_text: str, guardrail_id: str) -> GuardrailExecutionResult:
    started_at = perf_counter()
    logger.info(
        "NeMo guardrail execution started: "
        f"guardrail_id={guardrail_id}, input_length={len(input_text or '')}"
    )
    step = "parse_guardrail_id"
    try:
        guardrail_uuid = _to_uuid(guardrail_id)

        step = "lookup_guardrail"
        guardrail = await _get_guardrail(guardrail_uuid)

        step = "lookup_model_registry"
        model_config = await _get_model_registry_config(guardrail)

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
        options = {
            "rails": {
                "input": True,
                "dialog": False,
                "output": False,
                "retrieval": False,
                "tool_input": False,
                "tool_output": False,
            },
            "log": {
                "activated_rails": True,
                "llm_calls": True,
            },
        }
        messages = [{"role": "user", "content": input_text}]
        try:
            generated = rails.generate_async(messages=messages, options=options)
            if asyncio.iscoroutine(generated):
                generated = await generated
        except Exception as exc:  # noqa: BLE001
            # Colang 2.x does not support generation log options yet.
            if "log` option is not supported for Colang 2.0" not in str(exc):
                raise
            logger.warning(
                "NeMo guardrail retrying without llm log options because configuration is Colang 2.x: "
                f"guardrail_id={guardrail_id}"
            )
            fallback_options = {
                "rails": options["rails"],
            }
            generated = rails.generate_async(messages=messages, options=fallback_options)
            if asyncio.iscoroutine(generated):
                generated = await generated

        step = "extract_rails_log"
        activated_rails = _extract_activated_rails(generated)
        blocked_by_input_rail, blocked_rail_names = _is_input_rail_blocked(activated_rails)
        input_rails_count = sum(1 for rail in activated_rails if rail.get("type") == "input")
        logger.info(
            "NeMo guardrail rails log summary: "
            f"guardrail_id={guardrail_id}, activated_rails={len(activated_rails)}, "
            f"input_rails={input_rails_count}, blocked_by_input_rail={blocked_by_input_rail}, "
            f"blocked_input_rails={blocked_rail_names}"
        )
        if input_rails_count == 0:
            logger.warning(
                "NeMo guardrail executed with zero active input rails: "
                f"guardrail_id={guardrail_id}. Check config_yml rails.input.flows and prompts_yml task names."
            )

        llm_calls = _extract_llm_calls(generated)
        llm_usage = _summarize_llm_calls(llm_calls)
        logger.info(
            "NeMo guardrail llm usage summary: "
            f"guardrail_id={guardrail_id}, llm_calls={llm_usage['llm_calls_count']}, "
            f"input_tokens={llm_usage['input_tokens']}, output_tokens={llm_usage['output_tokens']}, "
            f"total_tokens={llm_usage['total_tokens']}, model={llm_usage['model']}, provider={llm_usage['provider']}"
        )

        step = "extract_output"
        output_text = _extract_generated_text(generated)

        step = "classify_action"
        action = _classify_action(
            input_text=input_text,
            output_text=output_text,
            blocked_by_input_rail=blocked_by_input_rail,
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


def clear_nemo_guardrails_cache() -> None:
    with _RAILS_CACHE_LOCK:
        entries = list(_RAILS_CACHE.values())
        _RAILS_CACHE.clear()
    logger.info(f"NeMo rails cache cleared: entries={len(entries)}")
    for entry in entries:
        _cleanup_cached_entry(entry)


def invalidate_nemo_guardrail_cache(guardrail_id: str | UUID) -> None:
    cache_id = str(guardrail_id)
    with _RAILS_CACHE_LOCK:
        entry = _RAILS_CACHE.pop(cache_id, None)
    if entry:
        logger.info(f"NeMo rails cache invalidated: guardrail_id={cache_id}")
    else:
        logger.info(f"NeMo rails cache invalidation skipped (not found): guardrail_id={cache_id}")
    _cleanup_cached_entry(entry)
