from __future__ import annotations

import importlib
import inspect
import os
import warnings
from typing import TYPE_CHECKING, Any

import orjson
from loguru import logger
from pydantic import PydanticDeprecatedSince20

from agentcore.custom.eval import eval_custom_component_code
from agentcore.schema.artifact import get_artifact_type, post_process_raw
from agentcore.schema.data import Data
from agentcore.services.deps import get_tracing_service, session_scope

if TYPE_CHECKING:
    from agentcore.custom.custom_node.node import Node
    from agentcore.custom.custom_node.custom_node import ExecutableNode
    from agentcore.events.event_manager import EventManager
    from agentcore.graph_langgraph import LangGraphVertex


def _get_builtin_source_code(vertex: LangGraphVertex) -> str | None:
    """For built-in agentcore components, get the latest source code.

    Uses two strategies:
    1. Component cache lookup — the cache is populated from .py files at startup.
    2. Metadata-based module reload — reads the module from disk.

    Returns the source code string if the component is a built-in, else None.
    """
    comp_name = vertex.base_name  # e.g. "HumanApproval" (from node ID prefix)
    display_name = vertex.display_name  # e.g. "Human Approval"

    # ── Strategy 1: Look up in the component cache ──
    # The cache is populated from the actual .py source files at startup,
    # so it always has the latest code even if the flow JSON is stale.
    try:
        from agentcore.interface.components import component_cache

        if component_cache.all_types_dict:
            for _category, components in component_cache.all_types_dict.items():
                if not isinstance(components, dict):
                    continue
                for cached_name, comp_data in components.items():
                    if not isinstance(comp_data, dict):
                        continue
                    # Match by class name (e.g. "HumanApproval") or display name
                    if cached_name == comp_name or cached_name == display_name:
                        template = comp_data.get("template", {})
                        code_field = template.get("code", {})
                        if isinstance(code_field, dict) and code_field.get("value"):
                            cache_code = code_field["value"]
                            logger.debug(
                                f"Refreshed built-in component '{comp_name}' from component cache "
                                f"(code_len={len(cache_code)})"
                            )
                            return cache_code
    except Exception as exc:
        logger.debug(f"Component cache lookup failed for '{comp_name}': {exc}")

    # ── Strategy 2: Metadata-based module reload ──
    node_info = vertex.data.get("node", {})
    metadata = node_info.get("metadata", {})
    module_path = metadata.get("module", "")

    if module_path.startswith("agentcore.components."):
        parts = module_path.rsplit(".", 1)
        if len(parts) == 2:
            py_module_path, _class_name = parts
            try:
                mod = importlib.import_module(py_module_path)
                importlib.reload(mod)
                source = inspect.getsource(mod)
                logger.info(f"Refreshed built-in component '{comp_name}' from {py_module_path}")
                return source
            except Exception as exc:
                logger.warning(f"Could not refresh built-in code for {module_path}: {exc}")

    return None


def instantiate_class(
    vertex: LangGraphVertex,
    user_id=None,
    event_manager: EventManager | None = None,
) -> Any:
    """Instantiate class from module type and key, and params."""
    vertex_type = vertex.vertex_type
    base_type = vertex.base_type
    logger.debug(f"Instantiating {vertex_type} of type {base_type}")

    if not base_type:
        msg = "No base type provided for vertex"
        raise ValueError(msg)

    custom_params = get_params(vertex.params)

    code = custom_params.pop("code")

    # For built-in components, always use the latest source from disk
    refreshed_code = _get_builtin_source_code(vertex)
    if refreshed_code is not None:
        code = refreshed_code

    class_object: type[ExecutableNode | Node] = eval_custom_component_code(code)
    custom_component: ExecutableNode | Node = class_object(
        _user_id=user_id,
        _parameters=custom_params,
        _vertex=vertex,
        _tracing_service=get_tracing_service(),
        _id=vertex.id,
    )
    if hasattr(custom_component, "set_event_manager"):
        custom_component.set_event_manager(event_manager)
    return custom_component, custom_params


async def get_instance_results(
    custom_component,
    custom_params: dict,
    vertex: LangGraphVertex,
    *,
    fallback_to_env_vars: bool = False,
    base_type: str = "component",
):
    custom_params = await update_params_with_load_from_db_fields(
        custom_component,
        custom_params,
        vertex.load_from_db_fields,
        fallback_to_env_vars=fallback_to_env_vars,
    )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)
        if base_type == "custom_components":
            return await build_custom_component(params=custom_params, custom_component=custom_component)
        if base_type == "component":
            return await build_component(params=custom_params, custom_component=custom_component)
        msg = f"Base type {base_type} not found."
        raise ValueError(msg)


def get_params(vertex_params):
    params = vertex_params
    params = convert_params_to_sets(params)
    params = convert_kwargs(params)
    return params.copy()


def convert_params_to_sets(params):
    """Convert certain params to sets."""
    if "allowed_special" in params:
        params["allowed_special"] = set(params["allowed_special"])
    if "disallowed_special" in params:
        params["disallowed_special"] = set(params["disallowed_special"])
    return params


def convert_kwargs(params):
    # Loop through items to avoid repeated lookups
    items_to_remove = []
    for key, value in params.items():
        if ("kwargs" in key or "config" in key) and isinstance(value, str):
            try:
                params[key] = orjson.loads(value)
            except orjson.JSONDecodeError:
                items_to_remove.append(key)

    # Remove invalid keys outside the loop to avoid modifying dict during iteration
    for key in items_to_remove:
        params.pop(key, None)

    return params


async def update_params_with_load_from_db_fields(
    custom_component: ExecutableNode,
    params,
    load_from_db_fields,
    *,
    fallback_to_env_vars=False,
):
    async with session_scope() as session:
        for field in load_from_db_fields:
            if field not in params or not params[field]:
                continue

            try:
                key = await custom_component.get_variable(name=params[field], field=field, session=session)
            except ValueError as e:
                if any(reason in str(e) for reason in ["User id is not set", "variable not found."]):
                    raise
                logger.debug(str(e))
                key = None

            if fallback_to_env_vars and key is None:
                key = os.getenv(params[field])
                if key:
                    logger.info(f"Using environment variable {params[field]} for {field}")
                else:
                    logger.error(f"Environment variable {params[field]} is not set.")

            params[field] = key if key is not None else None
            if key is None:
                logger.warning(f"Could not get value for {field}. Setting it to None.")

        return params


async def build_component(
    params: dict,
    custom_component: Node,
):
    # Now set the params as attributes of the custom_component
    custom_component.set_attributes(params)
    build_results, artifacts = await custom_component.build_results()

    return custom_component, build_results, artifacts


async def build_custom_component(params: dict, custom_component: ExecutableNode):
    if "retriever" in params and hasattr(params["retriever"], "as_retriever"):
        params["retriever"] = params["retriever"].as_retriever()

    # Determine if the build method is asynchronous
    is_async = inspect.iscoroutinefunction(custom_component.build)

    # New feature: the component has a list of outputs and we have
    # to check the vertex.edges to see which is connected (coulb be multiple)
    # and then we'll get the output which has the name of the method we should call.
    # the methods don't require any params because they are already set in the custom_component
    # so we can just call them

    if is_async:
        # Await the build method directly if it's async
        build_result = await custom_component.build(**params)
    else:
        # Call the build method directly if it's sync
        build_result = custom_component.build(**params)
    custom_repr = custom_component.custom_repr()
    if custom_repr is None and isinstance(build_result, dict | Data | str):
        custom_repr = build_result
    if not isinstance(custom_repr, str):
        custom_repr = str(custom_repr)
    raw = custom_component.repr_value
    if hasattr(raw, "data") and raw is not None:
        raw = raw.data

    elif hasattr(raw, "model_dump") and raw is not None:
        raw = raw.model_dump()
    if raw is None and isinstance(build_result, dict | Data | str):
        raw = build_result.data if isinstance(build_result, Data) else build_result

    artifact_type = get_artifact_type(custom_component.repr_value or raw, build_result)
    raw = post_process_raw(raw, artifact_type)
    artifact = {"repr": custom_repr, "raw": raw, "type": artifact_type}

    if custom_component._vertex is not None:
        custom_component._artifacts = {custom_component._vertex.outputs[0].get("name"): artifact}
        custom_component._results = {custom_component._vertex.outputs[0].get("name"): build_result}
        return custom_component, build_result, artifact

    msg = "Custom component does not have a vertex"
    raise ValueError(msg)
