# TARGET PATH: src/backend/base/agentcore/components/agents/a2a_client_component.py
"""A2A Client Component.

Calls an external A2A-compatible agent following the Google A2A protocol.
Discovers the agent via GET /.well-known/agent.json, then sends a message
via POST /rpc using JSON-RPC 2.0.

Optionally pre-processes the input locally with an LLM, tools, and
knowledge base before sending the enriched message to the remote agent.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx

from agentcore.base.child_agent.registry import ChildAgentRegistry
from agentcore.custom.custom_node.node import Node
from agentcore.io import (
    BoolInput,
    DropdownInput,
    HandleInput,
    IntInput,
    MultilineInput,
    Output,
    SecretStrInput,
    StrInput,
)
from agentcore.logging import logger
from agentcore.schema.a2a_jsonrpc import (
    A2AAgentCardResponse,
    A2AMessageContent,
    A2ASendParams,
    A2ASendResult,
    A2ATaskInfo,
    JsonRpcRequest,
    JsonRpcResponse,
)
from agentcore.schema.data import Data
from agentcore.schema.dotdict import dotdict
from agentcore.schema.message import Message
from agentcore.utils.constants import MESSAGE_SENDER_AI

LOCALHOST_HOST = os.getenv("LOCALHOST_HOST", "localhost")
LOCALHOST_A2A_URL_EXAMPLE = os.getenv(
    "LOCALHOST_A2A_URL_EXAMPLE",
    "http://localhost:7860/api/a2a/{agent-id}",
)


class A2AClientComponent(Node):
    """Component that calls an external A2A-compatible agent.

    Follows the Google A2A protocol:
    1. Discovers agent capabilities via GET <agent_url>/.well-known/agent.json
    2. Validates the agent card and supported methods
    3. Optionally pre-processes the input with a local LLM, tools, and KB
    4. Sends a message via POST <rpc_url> using JSON-RPC 2.0 (message/send)
    5. Parses the response and returns structured output
    """

    display_name: str = "A2A Client"
    description: str = (
        "Call an external A2A-compatible agent. Discovers capabilities via "
        "the agent card, then sends a message using JSON-RPC 2.0. "
        "Optionally pre-process the input with a local LLM, tools, and knowledge base."
    )
    documentation: str = "https://docs.agentcore.org/a2a-client"
    icon = "Globe"
    name = "A2AClient"
    beta = False

    inputs = [
        DropdownInput(
            name="agent_source",
            display_name="Agent Source",
            options=["Local Agent", "Remote URL"],
            value="Local Agent",
            info="Choose whether to call a local agent from this system or a remote agent via URL.",
            real_time_refresh=True,
        ),
        DropdownInput(
            name="local_agent_name",
            display_name="Local Agent",
            options=[],
            real_time_refresh=True,
            refresh_button=True,
            value=None,
            info="Select an agent from this system to call via A2A protocol.",
        ),
        StrInput(
            name="agent_url",
            display_name="Agent URL",
            info=(
                "Backend API URL of the A2A-compatible agent "
                f"(e.g., {LOCALHOST_A2A_URL_EXAMPLE}). "
                "This must be the backend API URL, not the frontend URL. "
                "The agent card will be fetched from <url>/.well-known/agent.json "
                "and the RPC endpoint will be read from the agent card."
            ),
            required=False,
        ),
        SecretStrInput(
            name="api_key",
            display_name="API Key",
            info=(
                "API key for authenticating with the remote agent. "
                "Sent in the header specified by the agent card (defaults to x-api-key)."
            ),
            required=False,
            value="",
        ),
        MultilineInput(
            name="input_message",
            display_name="Input Message",
            info=(
                "The message to send to the remote agent. "
                "Can also receive input from a previous component via the handle."
            ),
            required=True,
            input_types=["Message"],
        ),
        IntInput(
            name="timeout",
            display_name="Timeout (seconds)",
            info="Maximum time to wait for the agent to respond, in seconds.",
            value=120,
            advanced=True,
        ),
        StrInput(
            name="session_id",
            display_name="Session ID",
            info=(
                "Optional session ID for maintaining conversation context "
                "with the remote agent. If empty, each call is a new session."
            ),
            value="",
            advanced=True,
        ),
        BoolInput(
            name="verify_ssl",
            display_name="Verify SSL",
            info="Whether to verify SSL certificates when connecting to the remote agent.",
            value=True,
            advanced=True,
        ),
        # ── Optional pre-processing inputs ───────────────────────────
        HandleInput(
            name="llm",
            display_name="Pre-process LLM",
            input_types=["LanguageModel"],
            required=False,
            advanced=True,
            info=(
                "Optional: Connect a Language Model to pre-process the input "
                "message locally before sending it to the remote agent. "
                "When not connected, the input message is sent directly."
            ),
        ),
        HandleInput(
            name="tools",
            display_name="Pre-process Tools",
            input_types=["Tool"],
            is_list=True,
            required=False,
            advanced=True,
            info=(
                "Optional tools available to the pre-processing LLM. "
                "Only used when a Pre-process LLM is connected."
            ),
        ),
        HandleInput(
            name="knowledge_base",
            display_name="Knowledge Base",
            input_types=["Data", "Retriever", "DataFrame"],
            is_list=True,
            required=False,
            advanced=True,
            info=(
                "Optional knowledge base context for pre-processing. "
                "Text content will be injected into the pre-processing prompt."
            ),
        ),
        MultilineInput(
            name="pre_process_instructions",
            display_name="Pre-processing Instructions",
            info=(
                "Instructions for the local pre-processing LLM on how to "
                "enrich or transform the input before sending to the remote agent."
            ),
            value="",
            required=False,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            name="response",
            display_name="Response",
            method="call_agent",
        ),
        Output(
            name="agent_card",
            display_name="Agent Card",
            method="get_agent_card",
        ),
        Output(
            name="task_info",
            display_name="Task Info",
            method="get_task_info",
        ),
    ]

    def __init__(self, **data):
        super().__init__(**data)
        self._agent_card_cache: A2AAgentCardResponse | None = None
        self._last_task_info: A2ATaskInfo | None = None
        self._last_send_result: A2ASendResult | None = None
        self._resolved_url: str | None = None

    # ── Build config / dropdown population ───────────────────────────

    async def update_build_config(
        self, build_config: dotdict, field_value: Any, field_name: str | None = None
    ) -> dotdict:
        """Show/hide fields based on agent_source and populate local agent dropdown."""
        if field_name == "agent_source":
            is_local = field_value == "Local Agent"
            build_config["local_agent_name"]["show"] = is_local
            build_config["agent_url"]["show"] = not is_local
            build_config["api_key"]["show"] = not is_local

        if field_name in ("local_agent_name", "agent_source"):
            try:
                current_agent_id = None
                if hasattr(self, "graph") and self.graph:
                    current_agent_id = getattr(self.graph, "agent_id", None) or getattr(
                        self.graph, "flow_id", None
                    )
                agent_names = await ChildAgentRegistry.get_agent_names(
                    user_id=str(self.user_id),
                    exclude_agent_id=current_agent_id,
                )
                build_config["local_agent_name"]["options"] = agent_names
            except Exception as e:
                logger.warning(f"Error getting available agents: {e}")
                build_config["local_agent_name"]["options"] = []

        return build_config

    async def _resolve_agent_url(self) -> str:
        """Resolve the agent URL based on agent_source setting.

        For local agents: look up agent by name in DB, construct local A2A URL.
        For remote agents: return the user-provided URL as-is.
        """
        agent_source = getattr(self, "agent_source", "Remote URL")

        if agent_source == "Local Agent":
            agent_name = getattr(self, "local_agent_name", None)
            if not agent_name:
                msg = "No local agent selected"
                raise ValueError(msg)

            agent_info = await ChildAgentRegistry.get_agent_by_name(
                agent_name=agent_name,
                user_id=str(self.user_id),
            )
            if not agent_info:
                msg = f"Agent '{agent_name}' not found in the database"
                raise ValueError(msg)

            return f"http://{LOCALHOST_HOST}:{os.getenv('BACKEND_PORT', '7860')}/api/a2a/{agent_info.id}"

        # Remote URL mode
        url = getattr(self, "agent_url", "")
        if not url:
            msg = "Agent URL is required when using Remote URL mode"
            raise ValueError(msg)
        return url

    # ── Private helpers ──────────────────────────────────────────────

    def _build_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=30.0,
                read=float(self.timeout),
                write=30.0,
                pool=10.0,
            ),
            verify=self.verify_ssl,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=0,  # disable keep-alive to avoid stale connections
            ),
        )

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        url = str(url).strip()
        if not url:
            msg = "Agent URL cannot be empty"
            raise ValueError(msg)
        if not url.startswith(("http://", "https://")):
            # Default to http for localhost-like URLs and 127.0.0.1, https for everything else
            if url.startswith((LOCALHOST_HOST, "127.0.0.1")):
                url = f"http://{url}"
            else:
                url = f"https://{url}"
        url = url.rstrip("/")
        # Strip frontend path suffixes like /folder/{id}
        url = re.sub(r"/folder/[a-f0-9-]+$", "", url)
        return url

    async def _fetch_agent_card(self, client: httpx.AsyncClient) -> A2AAgentCardResponse:
        """GET <base_url>/.well-known/agent.json → validate and return agent card."""
        base_url = self._normalize_base_url(self._resolved_url)
        agent_card_url = f"{base_url}/.well-known/agent.json"

        logger.info(f"A2A Client: Fetching agent card from {agent_card_url}")

        try:
            response = await client.get(agent_card_url)
            response.raise_for_status()
        except httpx.InvalidURL as e:
            msg = f"Invalid agent URL '{agent_card_url}': {e}"
            logger.error(msg)
            raise ValueError(msg) from e
        except httpx.ConnectError as e:
            msg = f"Cannot reach agent at {agent_card_url}: {e}"
            logger.error(msg)
            raise ConnectionError(msg) from e
        except httpx.TimeoutException as e:
            msg = f"Timeout fetching agent card from {agent_card_url}"
            logger.error(msg)
            raise ConnectionError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Agent card endpoint returned HTTP {e.response.status_code}: {e}"
            logger.error(msg)
            raise ValueError(msg) from e

        try:
            card_data = response.json()
            agent_card = A2AAgentCardResponse(**card_data)
        except Exception as e:
            msg = f"Invalid agent card from {agent_card_url}: {e}"
            logger.error(msg)
            raise ValueError(msg) from e

        if "message/send" not in agent_card.supported_methods:
            msg = (
                f"Agent '{agent_card.name}' does not support 'message/send'. "
                f"Supported methods: {agent_card.supported_methods}"
            )
            raise ValueError(msg)

        logger.info(
            f"A2A Client: Discovered agent '{agent_card.name}' "
            f"v{agent_card.version} with capabilities: {agent_card.capabilities}"
        )
        return agent_card

    def _build_auth_headers(self, agent_card: A2AAgentCardResponse) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}

        # Include user ID for internal Agentcore-to-Agentcore calls
        user_id = getattr(self, "graph", None) and getattr(self.graph, "user_id", None)
        if user_id:
            headers["X-User-Id"] = str(user_id)

        api_key = self.api_key
        if not api_key:
            return headers

        auth_config = agent_card.authentication or {}
        auth_type = auth_config.get("type", "api_key")
        auth_header = auth_config.get("header", "x-api-key")

        if auth_type == "api_key":
            headers[auth_header] = api_key
        elif auth_type == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers["x-api-key"] = api_key

        return headers

    async def _send_rpc_message(
        self,
        client: httpx.AsyncClient,
        agent_card: A2AAgentCardResponse,
        message_text: str,
    ) -> A2ASendResult:
        """POST <agent_card.url> with JSON-RPC 2.0 message/send."""
        rpc_url = agent_card.url
        # Resolve relative URLs (e.g., "/api/a2a/{agent_id}/rpc") against base URL
        if rpc_url.startswith("/"):
            base_url = self._normalize_base_url(self._resolved_url)
            parsed = urlparse(base_url)
            rpc_url = f"{parsed.scheme}://{parsed.netloc}{rpc_url}"
        headers = self._build_auth_headers(agent_card)

        request_id = str(uuid.uuid4())
        send_params = A2ASendParams(
            message=A2AMessageContent(type="text", text=message_text),
            session_id=self.session_id if self.session_id else None,
        )
        rpc_request = JsonRpcRequest(
            method="message/send",
            params=send_params.model_dump(exclude_none=True),
            id=request_id,
        )

        logger.info(f"A2A Client: Sending message/send to {rpc_url} (request_id={request_id})")

        try:
            response = await client.post(
                rpc_url,
                headers=headers,
                json=rpc_request.model_dump(exclude_none=True),
            )
            response.raise_for_status()
        except httpx.InvalidURL as e:
            msg = f"Invalid RPC URL '{rpc_url}': {e}"
            logger.error(msg)
            raise ValueError(msg) from e
        except httpx.ConnectError as e:
            msg = f"Cannot reach agent RPC endpoint at {rpc_url}: {e}"
            logger.error(msg)
            raise ConnectionError(msg) from e
        except httpx.TimeoutException as e:
            msg = f"Timeout sending message to {rpc_url} (timeout={self.timeout}s)"
            logger.error(msg)
            raise TimeoutError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Agent RPC endpoint returned HTTP {e.response.status_code}: {e}"
            logger.error(msg)
            raise RuntimeError(msg) from e

        try:
            rpc_response_data = response.json()
            rpc_response = JsonRpcResponse(**rpc_response_data)
        except Exception as e:
            msg = f"Invalid JSON-RPC response from {rpc_url}: {e}"
            logger.error(msg)
            raise RuntimeError(msg) from e

        if rpc_response.error is not None:
            error = rpc_response.error
            msg = (
                f"Agent returned error (code={error.code}): {error.message}"
                + (f" - {error.data}" if error.data else "")
            )
            logger.error(msg)
            raise RuntimeError(msg)

        if rpc_response.result is None:
            msg = "Agent returned empty result"
            raise RuntimeError(msg)

        try:
            send_result = A2ASendResult(**rpc_response.result)
        except Exception as e:
            msg = f"Cannot parse agent response result: {e}"
            logger.error(msg)
            raise RuntimeError(msg) from e

        logger.info(
            f"A2A Client: Received response, task_id={send_result.task.id}, "
            f"status={send_result.task.status}"
        )
        return send_result

    def _extract_message_text(self) -> str:
        input_msg = self.input_message
        if isinstance(input_msg, Message):
            return input_msg.text or ""
        if isinstance(input_msg, str):
            return input_msg
        return str(input_msg)

    # ── Pre-processing helpers ───────────────────────────────────────

    def _extract_kb_context(self) -> str:
        """Extract text content from connected knowledge base sources."""
        kb_data = getattr(self, "knowledge_base", None) or []
        if not kb_data:
            return ""

        kb_texts: list[str] = []
        for item in kb_data:
            if hasattr(item, "data") and not isinstance(getattr(item, "text", None), str):
                data = item.data
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict) and "text" in entry:
                            kb_texts.append(entry["text"])
                        else:
                            kb_texts.append(str(entry))
                elif isinstance(data, dict):
                    kb_texts.append(str(data))
                else:
                    kb_texts.append(str(data))
            elif hasattr(item, "text") and isinstance(item.text, str) and item.text:
                kb_texts.append(item.text)
            else:
                kb_texts.append(str(item))

        if not kb_texts:
            return ""

        return "\n\nKNOWLEDGE BASE CONTEXT:\n" + "\n---\n".join(kb_texts[:10])

    @staticmethod
    def _coerce_tool_args(tool, args: dict) -> dict:
        """Coerce tool arguments to match expected schema types."""
        if not hasattr(tool, "args_schema") or tool.args_schema is None:
            return args
        try:
            schema = tool.args_schema.schema()
            props = schema.get("properties", {})
            coerced = dict(args)
            for param_name, param_def in props.items():
                ptype = param_def.get("type", "")
                if param_name not in coerced:
                    continue
                val = coerced[param_name]
                if ptype == "integer" and not isinstance(val, int):
                    try:
                        coerced[param_name] = int(val)
                    except (ValueError, TypeError):
                        coerced[param_name] = 0
                elif ptype == "number" and not isinstance(val, (int, float)):
                    try:
                        coerced[param_name] = float(val)
                    except (ValueError, TypeError):
                        coerced[param_name] = 0.0
                elif ptype == "boolean" and not isinstance(val, bool):
                    coerced[param_name] = str(val).lower() in ("true", "1", "yes")
            return coerced
        except Exception:
            return args

    async def _run_with_tools(
        self,
        llm,
        tools: list,
        prompt: str,
        max_iterations: int = 5,
    ) -> str:
        """Run the pre-processing LLM with tool-calling in a loop."""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        llm_with_tools = llm.bind_tools(tools)
        tool_map = {t.name: t for t in tools if hasattr(t, "name")}
        messages = [HumanMessage(content=prompt)]

        for _iteration in range(max_iterations):
            if hasattr(llm_with_tools, "ainvoke"):
                response = await llm_with_tools.ainvoke(messages)
            else:
                response = llm_with_tools.invoke(messages)
            messages.append(response)

            if hasattr(response, "tool_calls") and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", "")

                    logger.debug(f"A2A Client pre-process: tool call '{tool_name}'")

                    if tool_name in tool_map:
                        try:
                            coerced_args = self._coerce_tool_args(
                                tool_map[tool_name], tool_args
                            )
                            tool_result = await tool_map[tool_name].ainvoke(coerced_args)
                            tool_result_str = str(tool_result)
                        except Exception as e:
                            tool_result_str = f"Tool error: {e}"
                    else:
                        tool_result_str = f"Tool '{tool_name}' not found"

                    messages.append(ToolMessage(
                        content=tool_result_str,
                        tool_call_id=tool_id,
                    ))
            else:
                return response.content if hasattr(response, "content") else str(response)

        # Max iterations reached — return last response
        last = messages[-1]
        if isinstance(last, AIMessage):
            return last.content if hasattr(last, "content") else str(last)
        return str(last)

    async def _pre_process_with_llm(self, message_text: str) -> str:
        """Pre-process the input message using the local LLM.

        Builds a prompt from pre_process_instructions + KB context + user message,
        then dispatches to _run_with_tools (if tools connected) or simple LLM invoke.
        """
        llm = self.llm
        if not hasattr(llm, "invoke"):
            msg = "No valid LLM connected for pre-processing"
            raise ValueError(msg)

        # 1. Extract knowledge base context
        kb_context = self._extract_kb_context()

        # 2. Build the pre-processing prompt
        instructions = getattr(self, "pre_process_instructions", "") or ""
        parts: list[str] = []
        if instructions.strip():
            parts.append(instructions.strip())
        if kb_context:
            parts.append(kb_context)
        parts.append(f"\nUSER MESSAGE:\n{message_text}")
        full_prompt = "\n\n".join(parts)

        # 3. Flatten tools list (MCP Toolset can produce nested lists)
        raw_tools = getattr(self, "tools", None) or []
        all_tools: list = []
        if isinstance(raw_tools, list):
            for t in raw_tools:
                if isinstance(t, list):
                    all_tools.extend(t)
                else:
                    all_tools.append(t)
        elif raw_tools:
            all_tools = [raw_tools]

        # 4. Dispatch
        if all_tools and hasattr(llm, "bind_tools"):
            logger.info(f"A2A Client: Pre-processing with LLM + {len(all_tools)} tools")
            result = await self._run_with_tools(llm, all_tools, full_prompt)
        else:
            logger.info("A2A Client: Pre-processing with LLM (no tools)")
            if hasattr(llm, "ainvoke"):
                response = await llm.ainvoke(full_prompt)
            else:
                response = llm.invoke(full_prompt)
            result = response.content if hasattr(response, "content") else str(response)

        logger.info(f"A2A Client: Pre-processing complete, enriched message length={len(result)}")
        return result

    # ── Execution flow ───────────────────────────────────────────────

    async def _execute_full_flow(self) -> None:
        """Run discovery + send once, cache results for all output ports.

        If an LLM is connected, pre-processes the input message locally
        before sending the enriched message to the remote agent.
        """
        if self._last_send_result is not None:
            return

        # Resolve the agent URL (local agent lookup or remote URL)
        self._resolved_url = await self._resolve_agent_url()

        message_text = self._extract_message_text()
        if not message_text.strip():
            msg = "Input message cannot be empty"
            raise ValueError(msg)

        # Optional local pre-processing
        llm = getattr(self, "llm", None)
        if llm is not None and hasattr(llm, "invoke"):
            message_text = await self._pre_process_with_llm(message_text)
            if not message_text.strip():
                msg = "Pre-processing LLM returned empty output"
                raise ValueError(msg)

        async with self._build_http_client() as client:
            self._agent_card_cache = await self._fetch_agent_card(client)
            self._last_send_result = await self._send_rpc_message(
                client, self._agent_card_cache, message_text
            )
            self._last_task_info = self._last_send_result.task

    # ── Public output methods ────────────────────────────────────────

    async def call_agent(self) -> Message:
        """Send a message to the remote A2A agent and return the response."""
        await self._execute_full_flow()

        send_result = self._last_send_result
        agent_name = (
            self._agent_card_cache.name if self._agent_card_cache else "A2A Agent"
        )

        response_text = ""
        if send_result.content is not None:
            if send_result.content.text:
                response_text = send_result.content.text
            elif send_result.content.data:
                response_text = json.dumps(send_result.content.data, indent=2)

        if send_result.task.status == "failed":
            response_text = (
                f"[Agent task failed] Task ID: {send_result.task.id}\n"
                f"{response_text or 'No error details provided.'}"
            )

        return Message(
            text=response_text,
            sender=MESSAGE_SENDER_AI,
            sender_name=agent_name,
        )

    async def get_agent_card(self) -> Data:
        """Return the remote agent's card as structured Data."""
        await self._execute_full_flow()
        return Data(data=self._agent_card_cache.model_dump())

    async def get_task_info(self) -> Data:
        """Return the task metadata from the last message/send call."""
        await self._execute_full_flow()
        return Data(data=self._last_task_info.model_dump())
