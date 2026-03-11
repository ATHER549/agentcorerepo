from __future__ import annotations

import asyncio
import uuid
from typing import Any

from langchain_core.tools import StructuredTool  # noqa: TC002
from pydantic import BaseModel

from agentcore.base.agents.utils import maybe_unflatten_dict, safe_cache_get, safe_cache_set
from agentcore.base.mcp.util import create_input_schema_from_json_schema
from agentcore.custom.custom_node.node_with_cache import NodeWithCache
from agentcore.inputs.inputs import InputTypes  # noqa: TC001
from agentcore.io import DropdownInput, McpInput, MessageTextInput, Output
from agentcore.io.schema import flatten_schema, schema_to_agentcore_inputs
from agentcore.logging import logger
from agentcore.schema.dataframe import DataFrame
from agentcore.schema.message import Message


# ---------------------------------------------------------------------------
# Lightweight wrappers for remote tool results
# ---------------------------------------------------------------------------


class _RemoteContentItem(BaseModel):
    """Mimics an MCP content block so build_output() stays compatible."""
    type: str = "text"
    text: str | None = None
    mime_type: str | None = None
    data: str | None = None

    def model_dump(self, **kwargs):
        d = super().model_dump(**kwargs)
        return {k: v for k, v in d.items() if v is not None}


class _RemoteToolResult:
    """Wraps the microservice InvokeToolResponse dict so that
    ``result.content`` returns a list of _RemoteContentItem."""

    def __init__(self, data: dict):
        self._data = data
        self.content = [
            _RemoteContentItem(**item) for item in data.get("content", [])
        ]
        self.success = data.get("success", False)
        self.error = data.get("error")


class MCPToolsNode(NodeWithCache):
    schema_inputs: list = []
    tools: list[StructuredTool] = []
    _not_load_actions: bool = False
    _tool_cache: dict = {}
    _last_selected_server: str | None = None
    _server_id: str | None = None  # UUID of the resolved MCP server

    default_keys: list[str] = [
        "code",
        "_type",
        "tool_mode",
        "tool_placeholder",
        "mcp_server",
        "tool",
    ]

    display_name = "MCP Connector"
    description = "Use tools from a registered MCP server."
    icon = "Server"
    name = "MCPTools"

    inputs = [
        McpInput(
            name="mcp_server",
            display_name="MCP Server",
            info="Select the MCP Server that will be used by this component",
            real_time_refresh=True,
        ),
        DropdownInput(
            name="tool",
            display_name="Tool",
            options=[],
            value="",
            info="Select the tool to execute",
            show=False,
            required=True,
            real_time_refresh=True,
        ),
        MessageTextInput(
            name="tool_placeholder",
            display_name="Tool Placeholder",
            info="Placeholder for the tool",
            value="",
            show=False,
            tool_mode=False,
        ),
    ]

    outputs = [
        Output(display_name="Response", name="response", method="build_output"),
    ]

    def __init__(self, **data) -> None:
        super().__init__(**data)
        self._ensure_cache_structure()

    def _ensure_cache_structure(self):
        """Ensure the cache has the required structure."""
        servers_value = safe_cache_get(self._shared_component_cache, "servers")
        if servers_value is None:
            safe_cache_set(self._shared_component_cache, "servers", {})

        last_server_value = safe_cache_get(self._shared_component_cache, "last_selected_server")
        if last_server_value is None:
            safe_cache_set(self._shared_component_cache, "last_selected_server", "")

    def _get_session_context(self) -> str | None:
        """Get the Agentcore session ID for MCP session caching."""
        if hasattr(self, "graph") and hasattr(self.graph, "session_id"):
            session_id = self.graph.session_id
            server_name = ""
            mcp_server = getattr(self, "mcp_server", None)
            if isinstance(mcp_server, dict):
                server_name = mcp_server.get("name", "")
            elif mcp_server:
                server_name = str(mcp_server)
            return f"{session_id}_{server_name}" if session_id else None
        return None

    async def _resolve_server_id(self, server_name: str) -> str | None:
        """Look up the server UUID from its name via the MCP microservice."""
        from agentcore.services.mcp_service_client import fetch_mcp_servers_async

        servers = await fetch_mcp_servers_async(active_only=False)
        for srv in servers:
            if srv.get("server_name") == server_name:
                return str(srv["id"])
        return None

    def _make_remote_tool_coroutine(self, server_id: str, tool_name: str, arg_schema: type[BaseModel]):
        """Create an async coroutine that invokes a tool via the microservice."""

        async def tool_coroutine(*args, **kwargs):
            from agentcore.services.mcp_service_client import invoke_tool_via_service

            # Map positional args to field names
            field_names = list(arg_schema.model_fields.keys())
            provided_args = {}
            for i, arg in enumerate(args):
                if i >= len(field_names):
                    msg = "Too many positional arguments provided"
                    raise ValueError(msg)
                provided_args[field_names[i]] = arg
            provided_args.update(kwargs)

            # Validate
            try:
                validated = arg_schema.model_validate(provided_args)
            except Exception as e:
                msg = f"Invalid input: {e}"
                raise ValueError(msg) from e

            session_context = self._get_session_context()
            result_data = await invoke_tool_via_service(
                server_id=server_id,
                tool_name=tool_name,
                arguments=validated.model_dump(exclude_none=True),
                session_context=session_context,
            )

            return _RemoteToolResult(result_data)

        return tool_coroutine

    def _make_remote_tool_func(self, server_id: str, tool_name: str, arg_schema: type[BaseModel]):
        """Create a sync function wrapper for the tool."""

        def tool_func(*args, **kwargs):
            coroutine = self._make_remote_tool_coroutine(server_id, tool_name, arg_schema)
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(coroutine(*args, **kwargs))

        return tool_func

    async def _get_tools(self):
        """Get cached tools or update if necessary."""
        mcp_server = getattr(self, "mcp_server", None)
        if not self._not_load_actions:
            tools, _ = await self.update_tool_list(mcp_server)
            return tools
        return []

    async def _validate_schema_inputs(self, tool_obj) -> list[InputTypes]:
        """Validate and process schema inputs for a tool."""
        try:
            if not tool_obj or not hasattr(tool_obj, "args_schema"):
                msg = "Invalid tool object or missing input schema"
                raise ValueError(msg)

            flat_schema = flatten_schema(tool_obj.args_schema.schema())
            input_schema = create_input_schema_from_json_schema(flat_schema)
            if not input_schema:
                msg = f"Empty input schema for tool '{tool_obj.name}'"
                raise ValueError(msg)

            schema_inputs = schema_to_agentcore_inputs(input_schema)
            if not schema_inputs:
                msg = f"No input parameters defined for tool '{tool_obj.name}'"
                logger.warning(msg)
                return []

        except Exception as e:
            msg = f"Error validating schema inputs: {e!s}"
            logger.exception(msg)
            raise ValueError(msg) from e
        else:
            return schema_inputs

    async def build_output(self) -> DataFrame:
        """Build output by invoking the selected tool via the MCP microservice."""
        try:
            self.tools, _ = await self.update_tool_list()
            if self.tool != "":
                exec_tool = self._tool_cache[self.tool]
                tool_args = self.get_inputs_for_all_tools(self.tools)[self.tool]
                kwargs = {}
                for arg in tool_args:
                    value = getattr(self, arg.name, None)
                    if value is not None:
                        if isinstance(value, Message):
                            kwargs[arg.name] = value.text
                        else:
                            kwargs[arg.name] = value

                unflattened_kwargs = maybe_unflatten_dict(kwargs)

                output = await exec_tool.coroutine(**unflattened_kwargs)

                if not output.success:
                    return DataFrame(data=[{"error": output.error or "Tool invocation failed"}])

                tool_content = []
                for item in output.content:
                    item_dict = item.model_dump()
                    tool_content.append(item_dict)
                return DataFrame(data=tool_content)
            return DataFrame(data=[{"error": "You must select a tool"}])
        except Exception as e:
            msg = f"Error in build_output: {e!s}"
            logger.exception(msg)
            raise ValueError(msg) from e

    async def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None) -> dict:
        """Toggle the visibility of connection-specific fields based on the selected mode."""
        try:
            if field_name == "tool":
                try:
                    if len(self.tools) == 0:
                        try:
                            self.tools, build_config["mcp_server"]["value"] = await self.update_tool_list()
                            build_config["tool"]["options"] = [tool.name for tool in self.tools]
                            build_config["tool"]["placeholder"] = "Select a tool"
                        except (TimeoutError, asyncio.TimeoutError) as e:
                            msg = f"Timeout updating tool list: {e!s}"
                            logger.exception(msg)
                            if not build_config["tools_metadata"]["show"]:
                                build_config["tool"]["show"] = True
                                build_config["tool"]["options"] = []
                                build_config["tool"]["value"] = ""
                                build_config["tool"]["placeholder"] = "Timeout on MCP server"
                            else:
                                build_config["tool"]["show"] = False
                        except ValueError:
                            if not build_config["tools_metadata"]["show"]:
                                build_config["tool"]["show"] = True
                                build_config["tool"]["options"] = []
                                build_config["tool"]["value"] = ""
                                build_config["tool"]["placeholder"] = "Error on MCP Server"
                            else:
                                build_config["tool"]["show"] = False

                    if field_value == "":
                        return build_config
                    tool_obj = None
                    for tool in self.tools:
                        if tool.name == field_value:
                            tool_obj = tool
                            break
                    if tool_obj is None:
                        msg = f"Tool {field_value} not found in available tools: {self.tools}"
                        logger.warning(msg)
                        return build_config
                    await self._update_tool_config(build_config, field_value)
                except Exception as e:
                    build_config["tool"]["options"] = []
                    msg = f"Failed to update tools: {e!s}"
                    raise ValueError(msg) from e
                else:
                    return build_config
            elif field_name == "mcp_server":
                if not field_value:
                    build_config["tool"]["show"] = False
                    build_config["tool"]["options"] = []
                    build_config["tool"]["value"] = ""
                    build_config["tool"]["placeholder"] = ""
                    build_config["tool_placeholder"]["tool_mode"] = False
                    self.remove_non_default_keys(build_config)
                    return build_config

                build_config["tool_placeholder"]["tool_mode"] = True

                current_server_name = field_value.get("name") if isinstance(field_value, dict) else field_value
                _last_selected_server = safe_cache_get(self._shared_component_cache, "last_selected_server", "")

                if (_last_selected_server in (current_server_name, "")) and build_config["tool"]["show"]:
                    return build_config

                is_in_tool_mode = build_config["tools_metadata"]["show"]
                safe_cache_set(self._shared_component_cache, "last_selected_server", current_server_name)

                cached_tools = None
                if current_server_name:
                    servers_cache = safe_cache_get(self._shared_component_cache, "servers", {})
                    if isinstance(servers_cache, dict):
                        cached = servers_cache.get(current_server_name)
                        if cached is not None:
                            cached_tools = cached["tools"]
                            self.tools = cached_tools
                            self.tool_names = cached["tool_names"]
                            self._tool_cache = cached["tool_cache"]

                if not cached_tools:
                    self.tools = []

                self.remove_non_default_keys(build_config)

                if not is_in_tool_mode:
                    build_config["tool"]["show"] = True
                    if cached_tools:
                        build_config["tool"]["options"] = [tool.name for tool in cached_tools]
                        build_config["tool"]["placeholder"] = "Select a tool"
                    else:
                        build_config["tool"]["placeholder"] = "Loading tools..."
                        build_config["tool"]["options"] = []
                    build_config["tool"]["value"] = uuid.uuid4()
                else:
                    self._not_load_actions = True
                    build_config["tool"]["show"] = False

            elif field_name == "tool_mode":
                build_config["tool"]["placeholder"] = ""
                build_config["tool"]["show"] = not bool(field_value) and bool(build_config["mcp_server"])
                self.remove_non_default_keys(build_config)
                self.tool = build_config["tool"]["value"]
                if field_value:
                    self._not_load_actions = True
                else:
                    build_config["tool"]["value"] = uuid.uuid4()
                    build_config["tool"]["options"] = []
                    build_config["tool"]["show"] = True
                    build_config["tool"]["placeholder"] = "Loading tools..."
            elif field_name == "tools_metadata":
                self._not_load_actions = False

        except Exception as e:
            msg = f"Error in update_build_config: {e!s}"
            logger.exception(msg)
            raise ValueError(msg) from e
        else:
            return build_config

    async def _update_tool_config(self, build_config: dict, tool_name: str) -> None:
        """Update tool configuration with proper error handling."""
        if not self.tools:
            self.tools, build_config["mcp_server"]["value"] = await self.update_tool_list()

        if not tool_name:
            return

        tool_obj = next((tool for tool in self.tools if tool.name == tool_name), None)
        if not tool_obj:
            msg = f"Tool {tool_name} not found in available tools: {self.tools}"
            self.remove_non_default_keys(build_config)
            build_config["tool"]["value"] = ""
            logger.warning(msg)
            return

        try:
            current_values = {}
            for key, value in build_config.items():
                if key not in self.default_keys and isinstance(value, dict) and "value" in value:
                    current_values[key] = value["value"]

            input_schema_for_all_tools = self.get_inputs_for_all_tools(self.tools)
            self.remove_input_schema_from_build_config(build_config, tool_name, input_schema_for_all_tools)

            self.schema_inputs = await self._validate_schema_inputs(tool_obj)
            if not self.schema_inputs:
                msg = f"No input parameters to configure for tool '{tool_name}'"
                logger.info(msg)
                return

            for schema_input in self.schema_inputs:
                if not schema_input or not hasattr(schema_input, "name"):
                    msg = "Invalid schema input detected, skipping"
                    logger.warning(msg)
                    continue

                try:
                    name = schema_input.name
                    input_dict = schema_input.to_dict()
                    input_dict.setdefault("value", None)
                    input_dict.setdefault("required", True)

                    build_config[name] = input_dict

                    if name in current_values:
                        build_config[name]["value"] = current_values[name]

                except (AttributeError, KeyError, TypeError) as e:
                    msg = f"Error processing schema input {schema_input}: {e!s}"
                    logger.exception(msg)
                    continue
        except ValueError as e:
            msg = f"Schema validation error for tool {tool_name}: {e!s}"
            logger.exception(msg)
            self.schema_inputs = []
            return
        except (AttributeError, KeyError, TypeError) as e:
            msg = f"Error updating tool config: {e!s}"
            logger.exception(msg)
            raise ValueError(msg) from e

    def get_inputs_for_all_tools(self, tools: list) -> dict:
        """Get input schemas for all tools."""
        inputs = {}
        for tool in tools:
            if not tool or not hasattr(tool, "name"):
                continue
            try:
                flat_schema = flatten_schema(tool.args_schema.schema())
                input_schema = create_input_schema_from_json_schema(flat_schema)
                agentcore_inputs = schema_to_agentcore_inputs(input_schema)
                inputs[tool.name] = agentcore_inputs
            except (AttributeError, ValueError, TypeError, KeyError) as e:
                msg = f"Error getting inputs for tool {getattr(tool, 'name', 'unknown')}: {e!s}"
                logger.exception(msg)
                continue
        return inputs

    def remove_non_default_keys(self, build_config: dict) -> None:
        """Remove non-default keys from the build config."""
        for key in list(build_config.keys()):
            if key not in self.default_keys:
                build_config.pop(key)

    def remove_input_schema_from_build_config(
        self, build_config: dict, tool_name: str, input_schema: dict[list[InputTypes], Any]
    ):
        """Remove the input schema for the tool from the build config."""
        input_schema = {k: v for k, v in input_schema.items() if k != tool_name}
        for value in input_schema.values():
            for _input in value:
                if _input.name in build_config:
                    build_config.pop(_input.name)

    async def update_tool_list(self, mcp_server_value=None):
        """Fetch tools from the MCP microservice and reconstruct StructuredTool objects."""
        mcp_server = mcp_server_value if mcp_server_value is not None else getattr(self, "mcp_server", None)
        server_name = None
        server_config_from_value = None
        if isinstance(mcp_server, dict):
            server_name = mcp_server.get("name")
            server_config_from_value = mcp_server.get("config")
        else:
            server_name = mcp_server
        if not server_name:
            self.tools = []
            return [], {"name": server_name, "config": server_config_from_value}

        # Use shared cache if available
        servers_cache = safe_cache_get(self._shared_component_cache, "servers", {})
        cached = servers_cache.get(server_name) if isinstance(servers_cache, dict) else None

        if cached is not None:
            self.tools = cached["tools"]
            self.tool_names = cached["tool_names"]
            self._tool_cache = cached["tool_cache"]
            self._server_id = cached.get("server_id")
            server_config_from_value = cached["config"]
            return self.tools, {"name": server_name, "config": server_config_from_value}

        try:
            from agentcore.services.mcp_service_client import list_tools_via_service

            # Resolve server_id from server_name
            server_id = await self._resolve_server_id(server_name)
            if not server_id:
                logger.warning(f"MCP server '{server_name}' not found in registry")
                self.tools = []
                return [], {"name": server_name, "config": server_config_from_value}

            self._server_id = server_id
            session_context = self._get_session_context()

            # Call microservice to discover tools
            tool_schemas = await list_tools_via_service(server_id, session_context)

            # Reconstruct StructuredTool objects from returned JSON schemas
            tool_list: list[StructuredTool] = []
            tool_cache: dict[str, StructuredTool] = {}

            for ts in tool_schemas:
                tool_name = ts["name"]
                tool_desc = ts.get("description", "")
                raw_input_schema = ts.get("input_schema", {"type": "object", "properties": {}})

                try:
                    args_schema = create_input_schema_from_json_schema(raw_input_schema)
                    if not args_schema:
                        logger.warning(f"Could not create schema for tool '{tool_name}'")
                        continue

                    tool_obj = StructuredTool(
                        name=tool_name,
                        description=tool_desc,
                        args_schema=args_schema,
                        func=self._make_remote_tool_func(server_id, tool_name, args_schema),
                        coroutine=self._make_remote_tool_coroutine(server_id, tool_name, args_schema),
                        tags=[tool_name],
                        metadata={"server_name": server_name},
                    )
                    tool_list.append(tool_obj)
                    tool_cache[tool_name] = tool_obj
                except (ConnectionError, TimeoutError, OSError, ValueError) as e:
                    logger.error(f"Failed to create tool '{tool_name}': {e}")
                    msg = f"Failed to create tool '{tool_name}': {e}"
                    raise ValueError(msg) from e

            self.tool_names = [tool.name for tool in tool_list if hasattr(tool, "name")]
            self._tool_cache = tool_cache
            self.tools = tool_list

            # Cache the result
            cache_data = {
                "tools": tool_list,
                "tool_names": self.tool_names,
                "tool_cache": tool_cache,
                "config": server_config_from_value,
                "server_id": server_id,
            }

            current_servers_cache = safe_cache_get(self._shared_component_cache, "servers", {})
            if isinstance(current_servers_cache, dict):
                current_servers_cache[server_name] = cache_data
                safe_cache_set(self._shared_component_cache, "servers", current_servers_cache)

            logger.info(f"Loaded {len(tool_list)} tools from MCP server '{server_name}' via microservice")
            return tool_list, {"name": server_name, "config": server_config_from_value}
        except (TimeoutError, asyncio.TimeoutError) as e:
            msg = f"Timeout updating tool list: {e!s}"
            logger.exception(msg)
            raise TimeoutError(msg) from e
        except Exception as e:
            msg = f"Error updating tool list: {e!s}"
            logger.exception(msg)
            raise ValueError(msg) from e
