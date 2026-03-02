# TARGET PATH: src/backend/base/agentcore/components/agents/a2a_component.py
"""A2A (Agent-to-Agent) Agents Component.

This component implements Google's A2A protocol for multi-agent communication,
enabling dynamic agent-to-agent task delegation and routing.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentcore.base.a2a.protocol import A2AProtocol
from agentcore.custom.custom_node.node import Node
from agentcore.field_typing.range_spec import RangeSpec
from agentcore.io import (
    BoolInput,
    DropdownInput,
    HandleInput,
    MultilineInput,
    Output,
    SliderInput,
    StrInput,
    TableInput,
)
from agentcore.logging import logger
from agentcore.schema.data import Data
from agentcore.schema.dotdict import dotdict
from agentcore.schema.message import Message
from agentcore.schema.table import EditMode
from agentcore.utils.constants import MESSAGE_SENDER_AI


class A2AAgentsComponent(Node):
    """Component for Agent-to-Agent communication using Google A2A protocol.

    This component creates a group of agents that communicate dynamically,
    with each agent deciding whether to route to another agent or return
    a final response using ROUTE_TO directives.
    """

    display_name: str = "A2A Agents"
    description: str = (
        "Create a group of agents that communicate with each other using dynamic routing. "
    )
    documentation: str = "https://docs.agentcore.org/a2a-agents"
    icon = "Network"
    name = "A2AAgents"
    beta = False

    inputs = [
        # ===== Agent Definitions Table =====
        TableInput(
            name="agent_definitions",
            display_name="Agents",
            info="Define agents by adding rows. Each row is one agent. Minimum 2 agents required.",
            required=True,
            real_time_refresh=True,
            table_schema=[
                {
                    "name": "name",
                    "display_name": "Agent Name",
                    "type": "str",
                    "description": "Unique name for this agent.",
                    "default": "Agent",
                    "edit_mode": EditMode.INLINE,
                },
                {
                    "name": "instructions",
                    "display_name": "Instructions",
                    "type": "str",
                    "description": "System prompt / instructions for this agent.",
                    "default": "You are a helpful assistant.",
                    "edit_mode": EditMode.POPOVER,
                },
            ],
            value=[
                {
                    "name": "Agent 1",
                    "instructions": "You are a helpful assistant that analyzes the input and provides insights.",
                },
                {
                    "name": "Agent 2",
                    "instructions": "You are a research assistant that expands on the previous analysis.",
                },
            ],
        ),
        # ===== Default Agent 1 & 2 Handles (more generated dynamically) =====
        HandleInput(
            name="agent_1_llm",
            display_name="Agent 1 LLM",
            input_types=["LanguageModel"],
            info="Language Model for Agent 1",
            required=True,
        ),
        HandleInput(
            name="agent_1_tools",
            display_name="Agent 1 Tools",
            input_types=["Tool"],
            is_list=True,
            required=False,
            info="Tools available to Agent 1 (optional)",
        ),
        HandleInput(
            name="agent_1_kb",
            display_name="Agent 1 Knowledge Base",
            input_types=["Data", "Retriever", "DataFrame"],
            is_list=True,
            required=False,
            info="Knowledge base sources for Agent 1 (optional)",
        ),
        HandleInput(
            name="agent_2_llm",
            display_name="Agent 2 LLM",
            input_types=["LanguageModel"],
            info="Language Model for Agent 2",
            required=True,
        ),
        HandleInput(
            name="agent_2_tools",
            display_name="Agent 2 Tools",
            input_types=["Tool"],
            is_list=True,
            required=False,
            info="Tools available to Agent 2 (optional)",
        ),
        HandleInput(
            name="agent_2_kb",
            display_name="Agent 2 Knowledge Base",
            input_types=["Data", "Retriever", "DataFrame"],
            is_list=True,
            required=False,
            info="Knowledge base sources for Agent 2 (optional)",
        ),
        # ===== Routing Configuration =====
        BoolInput(
            name="smart_routing",
            display_name="Smart Routing",
            info="When enabled (default), an LLM evaluates the task and automatically selects the best starting agent based on their instructions.",
            value=True,
            advanced=True,
        ),
        SliderInput(
            name="max_iterations",
            display_name="Max Iterations",
            value=10,
            info="Maximum agent invocations (safety guard to prevent infinite loops)",
            range_spec=RangeSpec(min=2, max=50, step=1),
            advanced=True,
        ),
        DropdownInput(
            name="starting_agent",
            display_name="Starting Agent (Manual)",
            options=["Agent 1", "Agent 2"],
            value="Agent 1",
            info="Manually select which agent receives the initial task. Only used when Smart Routing is disabled.",
            advanced=True,
        ),
        StrInput(
            name="starting_agent_override",
            display_name="Starting Agent Override",
            info="Dynamic input to override starting agent. Pass agent name from parent flows. Takes priority over dropdown but not Smart Routing.",
            value="",
            advanced=True,
        ),
        # ===== Task Input =====
        MultilineInput(
            name="task",
            display_name="Task",
            info="The initial task/message to process through the agents",
            value="",
            required=True,
        ),
        MultilineInput(
            name="context",
            display_name="Additional Context",
            info="Optional additional context to provide to all agents",
            value="",
            advanced=True,
        ),
        # ===== Logging =====
        BoolInput(
            name="save_conversation_log",
            display_name="Save Conversation Log",
            info="Save the full agent communication log to a JSON file for verification",
            value=True,
            advanced=True,
        ),
        StrInput(
            name="log_directory",
            display_name="Log Directory",
            info="Directory to save conversation logs. Each conversation gets a separate timestamped file.",
            value="a2a_logs",
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            name="response",
            display_name="Response",
            method="run_a2a",
        ),
        Output(
            name="conversation_log",
            display_name="Conversation Log",
            method="get_conversation_log",
        ),
    ]

    def __init__(self, **data):
        super().__init__(**data)
        self._protocol = A2AProtocol()
        self._conversation_log: list[dict] = []
        self._detailed_log: list[dict] = []

    async def update_build_config(
        self, build_config: dotdict, field_value: Any, field_name: str | None = None
    ) -> dotdict:
        """Dynamically generate per-agent handle fields when the agents table changes."""
        if field_name == "agent_definitions":
            if isinstance(field_value, list):
                agent_defs = [row for row in field_value if isinstance(row, dict)]
            else:
                agent_defs = []

            num_agents = len(agent_defs)

            existing_agent_keys = set()
            for key in list(build_config.keys()):
                if key.startswith("agent_") and key.split("_")[1].isdigit():
                    existing_agent_keys.add(key)

            needed_keys = set()
            for i in range(num_agents):
                idx = i + 1
                needed_keys.update({
                    f"agent_{idx}_llm",
                    f"agent_{idx}_tools",
                    f"agent_{idx}_kb",
                })

            for key in existing_agent_keys - needed_keys:
                build_config.pop(key, None)

            for i, agent_def in enumerate(agent_defs):
                idx = i + 1
                agent_name = agent_def.get("name", f"Agent {idx}")

                llm_key = f"agent_{idx}_llm"
                tools_key = f"agent_{idx}_tools"
                kb_key = f"agent_{idx}_kb"

                if llm_key not in build_config:
                    build_config[llm_key] = HandleInput(
                        name=llm_key,
                        display_name=f"{agent_name} LLM",
                        input_types=["LanguageModel"],
                        info=f"Language Model for {agent_name}",
                        required=True,
                    ).to_dict()
                else:
                    build_config[llm_key]["display_name"] = f"{agent_name} LLM"
                    build_config[llm_key]["info"] = f"Language Model for {agent_name}"

                if tools_key not in build_config:
                    build_config[tools_key] = HandleInput(
                        name=tools_key,
                        display_name=f"{agent_name} Tools",
                        input_types=["Tool"],
                        is_list=True,
                        required=False,
                        info=f"Tools available to {agent_name} (optional)",
                    ).to_dict()
                else:
                    build_config[tools_key]["display_name"] = f"{agent_name} Tools"
                    build_config[tools_key]["info"] = f"Tools available to {agent_name} (optional)"

                if kb_key not in build_config:
                    build_config[kb_key] = HandleInput(
                        name=kb_key,
                        display_name=f"{agent_name} Knowledge Base",
                        input_types=["Data", "Retriever", "DataFrame"],
                        is_list=True,
                        required=False,
                        info=f"Knowledge base sources for {agent_name} (optional)",
                    ).to_dict()
                else:
                    build_config[kb_key]["display_name"] = f"{agent_name} Knowledge Base"
                    build_config[kb_key]["info"] = f"Knowledge base sources for {agent_name} (optional)"

            if "starting_agent" in build_config:
                agent_names = [
                    row.get("name", f"Agent {i+1}")
                    for i, row in enumerate(agent_defs)
                ]
                build_config["starting_agent"]["options"] = agent_names if agent_names else ["Agent 1"]
                current_value = build_config["starting_agent"].get("value", "")
                if current_value not in agent_names:
                    build_config["starting_agent"]["value"] = agent_names[0] if agent_names else "Agent 1"

        return build_config

    def _get_active_agents(self) -> list[dict[str, Any]]:
        """Get list of active agent configurations from the table."""
        agents = []

        agent_defs = getattr(self, "agent_definitions", [])
        if not isinstance(agent_defs, list):
            agent_defs = []

        for i, agent_def in enumerate(agent_defs):
            if not isinstance(agent_def, dict):
                continue

            idx = i + 1
            name = agent_def.get("name", f"Agent {idx}")
            instructions = agent_def.get("instructions", "You are a helpful assistant.")

            llm = getattr(self, f"agent_{idx}_llm", None)
            tools = getattr(self, f"agent_{idx}_tools", None) or []
            kb = getattr(self, f"agent_{idx}_kb", None) or []

            all_tools = []
            if isinstance(tools, list):
                for t in tools:
                    if isinstance(t, list):
                        all_tools.extend(t)
                    else:
                        all_tools.append(t)
            else:
                all_tools = [tools] if tools else []

            agents.append({
                "id": f"agent-{idx}",
                "name": name,
                "prompt": instructions,
                "llm": llm,
                "tools": all_tools,
                "knowledge_base": kb if isinstance(kb, list) else [],
            })

        return agents

    def _get_starting_agent_id(self, agents_config: list[dict[str, Any]]) -> str:
        """Get the starting agent ID based on the starting_agent setting or override."""
        override = getattr(self, "starting_agent_override", "")
        if override and override.strip():
            override = override.strip()
            for agent in agents_config:
                if agent["name"].lower() == override.lower():
                    logger.info(f"Starting agent override matched: {agent['name']} -> {agent['id']}")
                    return agent["id"]
            logger.warning(f"Starting agent override '{override}' not found, using dropdown setting")

        starting_agent_name = getattr(self, "starting_agent", "")
        for agent in agents_config:
            if agent["name"] == starting_agent_name:
                return agent["id"]

        return agents_config[0]["id"]

    async def _smart_route_to_agent(self, agents_config: list[dict[str, Any]], task: str) -> str:
        """Use LLM to determine which agent should handle the task first."""
        router_llm = agents_config[0]["llm"]

        agent_descriptions = "\n".join([
            f"- {agent['name']}: {agent['prompt'][:200]}..."
            if len(agent['prompt']) > 200 else f"- {agent['name']}: {agent['prompt']}"
            for agent in agents_config
        ])

        routing_prompt = f"""You are a task router. Based on the task below, determine which agent should handle it first.

Available Agents:
{agent_descriptions}

Task: {task}

Respond with ONLY the agent name that should handle this task. Just the name, nothing else."""

        try:
            if hasattr(router_llm, "ainvoke"):
                response = await router_llm.ainvoke(routing_prompt)
            else:
                response = router_llm.invoke(routing_prompt)

            if hasattr(response, "content"):
                selected_agent = response.content.strip()
            else:
                selected_agent = str(response).strip()

            for agent in agents_config:
                if agent["name"].lower() == selected_agent.lower():
                    logger.info(f"Smart routing selected: {agent['name']} -> {agent['id']}")
                    self._detailed_log.append({
                        "event": "smart_routing",
                        "timestamp": datetime.now().isoformat(),
                        "selected_agent": agent["name"],
                        "reason": f"LLM determined '{selected_agent}' is best suited for the task",
                    })
                    return agent["id"]

            for agent in agents_config:
                if selected_agent.lower() in agent["name"].lower() or agent["name"].lower() in selected_agent.lower():
                    logger.info(f"Smart routing partial match: {agent['name']} -> {agent['id']}")
                    return agent["id"]

            logger.warning(f"Smart routing could not match '{selected_agent}', falling back to first agent")
        except Exception as e:
            logger.warning(f"Smart routing failed: {e}, falling back to first agent")

        return agents_config[0]["id"]

    async def run_a2a(self) -> Message:
        """Execute the A2A workflow with dynamic agent routing."""
        agents_config = self._get_active_agents()

        if len(agents_config) < 2:
            msg = "A2A protocol requires at least 2 agents"
            raise ValueError(msg)

        self._detailed_log = [{
            "event": "workflow_start",
            "timestamp": datetime.now().isoformat(),
            "routing_mode": "dynamic",
            "active_agents": [{"id": a["id"], "name": a["name"]} for a in agents_config],
            "task": self.task,
            "context": self.context if self.context else None,
        }]

        agent_handlers = await self._create_agent_handlers(agents_config)

        initial_input = self.task
        if self.context:
            initial_input = f"Context: {self.context}\n\nTask: {self.task}"

        try:
            max_iterations = int(getattr(self, "max_iterations", 10))

            smart_routing_enabled = getattr(self, "smart_routing", True)
            if smart_routing_enabled:
                starting_agent_id = await self._smart_route_to_agent(agents_config, initial_input)
            else:
                starting_agent_id = self._get_starting_agent_id(agents_config)

            final_result, message_history = await self._protocol.run_dynamic(
                agent_configs=[{"id": a["id"], "name": a["name"], "prompt": a["prompt"]} for a in agents_config],
                initial_input=initial_input,
                agent_handlers=agent_handlers,
                max_iterations=max_iterations,
                starting_agent=starting_agent_id,
            )

            self._conversation_log = [
                {
                    "sender": msg.sender_id,
                    "receiver": msg.receiver_id,
                    "content": msg.content,
                    "type": msg.message_type.value,
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in message_history
            ]

            self._detailed_log.append({
                "event": "workflow_complete",
                "timestamp": datetime.now().isoformat(),
                "final_result_length": len(final_result),
                "total_messages": len(message_history),
            })

            if getattr(self, "save_conversation_log", True):
                self._save_log_to_file()

            return Message(
                text=final_result,
                sender=MESSAGE_SENDER_AI,
                sender_name="A2A Agents",
            )

        except Exception as e:
            self._detailed_log.append({
                "event": "workflow_error",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            })
            if getattr(self, "save_conversation_log", True):
                self._save_log_to_file()
            logger.error(f"A2A execution error: {e}")
            raise

    def _save_log_to_file(self):
        """Save the conversation log to a timestamped JSON file."""
        try:
            log_dir = Path(getattr(self, "log_directory", "a2a_logs"))
            log_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"a2a_log_{timestamp}.json"
            log_path = log_dir / filename

            full_log = {
                "workflow_details": self._detailed_log,
                "conversation": self._conversation_log,
                "summary": {
                    "total_agents": len(getattr(self, "agent_definitions", [])),
                    "total_messages": len(self._conversation_log),
                    "saved_at": datetime.now().isoformat(),
                }
            }
            with open(log_path, "w") as f:
                json.dump(full_log, f, indent=2)
            logger.info(f"A2A conversation log saved to: {log_path.absolute()}")
        except Exception as e:
            logger.warning(f"Failed to save conversation log: {e}")

    async def get_conversation_log(self) -> Data:
        """Get the conversation log between agents."""
        if not self._conversation_log:
            await self.run_a2a()

        return Data(data={
            "workflow_details": self._detailed_log,
            "conversation": self._conversation_log,
        })

    @staticmethod
    def _coerce_tool_args(tool, args: dict) -> dict:
        """Coerce tool arguments to match expected schema types."""
        if not hasattr(tool, "args_schema") or tool.args_schema is None:
            # No schema available (e.g. MCP tools) — remove None values
            # since MCP servers reject null for typed params
            return {k: v for k, v in args.items() if v is not None}

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
                        del coerced[param_name]

                elif ptype == "number" and not isinstance(val, (int, float)):
                    try:
                        coerced[param_name] = float(val)
                    except (ValueError, TypeError):
                        del coerced[param_name]

                elif ptype == "boolean" and not isinstance(val, bool):
                    coerced[param_name] = str(val).lower() in ("true", "1", "yes")

            # Remove remaining None values
            return {k: v for k, v in coerced.items() if v is not None}
        except Exception:
            return {k: v for k, v in args.items() if v is not None}

    @staticmethod
    def _extract_tool_result_text(tool_result) -> str:
        """Extract clean text from a tool result, handling MCP CallToolResult objects."""
        if isinstance(tool_result, str):
            return tool_result

        # MCP CallToolResult has .content (list of TextContent/etc) and .isError
        if hasattr(tool_result, "content") and isinstance(tool_result.content, list):
            texts = []
            for item in tool_result.content:
                if hasattr(item, "text"):
                    texts.append(item.text)
                else:
                    texts.append(str(item))
            return "\n".join(texts)

        if hasattr(tool_result, "content"):
            return str(tool_result.content)

        return str(tool_result)

    async def _run_agent_with_tools(
        self,
        llm,
        tools: list,
        prompt: str,
        agent_name: str,
        agent_id: str,
        max_tool_iterations: int = 5,
    ) -> str:
        """Run an agent with tool-calling capability using bind_tools."""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        # Monkey-patch langchain_google_genai to fix array schemas missing 'items'.
        original_fn = None
        try:
            from langchain_google_genai import _function_utils

            original_fn = _function_utils._format_json_schema_to_gapic

            def _patched_format(schema):
                if isinstance(schema, dict) and schema.get("type") == "array" and "items" not in schema:
                    schema = {**schema, "items": {"type": "string"}}
                return original_fn(schema)

            _function_utils._format_json_schema_to_gapic = _patched_format
        except ImportError:
            pass

        try:
            llm_with_tools = llm.bind_tools(tools)
            tool_map = {t.name: t for t in tools if hasattr(t, "name")}

            messages = [HumanMessage(content=prompt)]

            for _iteration in range(max_tool_iterations):
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

                        self._detailed_log.append({
                            "event": "tool_call",
                            "agent_id": agent_id,
                            "agent_name": agent_name,
                            "tool_name": tool_name,
                            "timestamp": datetime.now().isoformat(),
                        })

                        if tool_name in tool_map:
                            try:
                                coerced_args = self._coerce_tool_args(
                                    tool_map[tool_name], tool_args
                                )
                                tool_result = await tool_map[tool_name].ainvoke(coerced_args)
                                tool_result_str = self._extract_tool_result_text(tool_result)
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

            last_response = messages[-1]
            if hasattr(last_response, "content"):
                return last_response.content if isinstance(last_response.content, str) else str(last_response.content)
            return str(last_response)
        finally:
            if original_fn is not None:
                try:
                    from langchain_google_genai import _function_utils
                    _function_utils._format_json_schema_to_gapic = original_fn
                except ImportError:
                    pass

    async def _create_agent_handlers(
        self,
        agents_config: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create handler functions for each agent with dynamic routing instructions."""
        handlers = {}

        all_agent_names = [config["name"] for config in agents_config]

        for config in agents_config:
            agent_id = config["id"]
            agent_prompt = config["prompt"]
            agent_name = config["name"]
            agent_llm = config["llm"]
            agent_tools = config.get("tools", [])
            agent_kb = config.get("knowledge_base", [])

            async def create_handler(
                prompt: str,
                name: str,
                llm,
                aid: str,
                agent_names: list[str],
                tools: list,
                kb_data: list,
                all_configs: list[dict[str, Any]],
            ):
                async def handler(input_text: str) -> str:
                    self._detailed_log.append({
                        "event": "agent_invoked",
                        "agent_id": aid,
                        "agent_name": name,
                        "timestamp": datetime.now().isoformat(),
                        "input_length": len(input_text),
                        "input_preview": input_text[:200] + "..." if len(input_text) > 200 else input_text,
                        "has_tools": len(tools) > 0,
                        "has_knowledge_base": len(kb_data) > 0,
                    })

                    # Build descriptions of other agents with their capabilities
                    other_agent_info = []
                    for other in all_configs:
                        if other["name"] != name:
                            desc = other["prompt"][:150]
                            other_agent_info.append(f"  - {other['name']}: {desc}")
                    agent_capabilities = "\n".join(other_agent_info)

                    routing_instruction = f"""

ROUTING INSTRUCTIONS:
You are part of a multi-agent system with dynamic routing. After processing the input, you MUST end your response with EXACTLY ONE of these directives on its own line:

1. ROUTE_TO: <agent_name>
   Use this to pass the task to another agent for further processing.

2. FINAL_RESPONSE:
   Use this when ALL parts of the task are fully complete.

Available agents and their capabilities:
{agent_capabilities}

Guidelines:
- If ANY part of the original task remains unfinished by you, ROUTE_TO the agent best suited for it.
- If another agent's capabilities match remaining task requirements, ALWAYS route to them.
- Only use FINAL_RESPONSE when the ENTIRE task (all parts) is complete.
- Do NOT include meta-commentary about your process (e.g. "I received the content...", "Now I will...", "The task is complete."). Only output the actual content or result.

IMPORTANT: Your response MUST end with either "ROUTE_TO: <agent_name>" or "FINAL_RESPONSE:" on its own line."""

                    kb_context = ""
                    if kb_data:
                        kb_texts = []
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
                        if kb_texts:
                            kb_context = "\n\nKNOWLEDGE BASE CONTEXT:\n" + "\n---\n".join(kb_texts[:10])

                    tool_desc = ""
                    if tools:
                        tool_names = [t.name for t in tools if hasattr(t, "name")]
                        if tool_names:
                            tool_desc = f"\n\nAVAILABLE TOOLS: {', '.join(tool_names)}\nYou can call tools to assist with the task."

                    full_prompt = f"""You are {name}.

{prompt}{kb_context}{tool_desc}
{routing_instruction}

Process the following input:

{input_text}"""

                    if llm is None:
                        error_msg = f"[{name}] Error: No LLM connected for this agent"
                        self._detailed_log.append({
                            "event": "agent_error",
                            "agent_id": aid,
                            "agent_name": name,
                            "timestamp": datetime.now().isoformat(),
                            "error": "No LLM connected",
                        })
                        return error_msg

                    try:
                        if tools and hasattr(llm, "bind_tools"):
                            result = await self._run_agent_with_tools(
                                llm, tools, full_prompt, name, aid
                            )
                        elif hasattr(llm, "ainvoke"):
                            response = await llm.ainvoke(full_prompt)
                            if hasattr(response, "content"):
                                result = response.content
                            else:
                                result = str(response)
                        elif hasattr(llm, "invoke"):
                            response = llm.invoke(full_prompt)
                            if hasattr(response, "content"):
                                result = response.content
                            else:
                                result = str(response)
                        else:
                            result = f"[{name}] processed: {input_text}"

                        self._detailed_log.append({
                            "event": "agent_response",
                            "agent_id": aid,
                            "agent_name": name,
                            "timestamp": datetime.now().isoformat(),
                            "output_length": len(result),
                            "output_preview": result[:200] + "..." if len(result) > 200 else result,
                        })

                        return result

                    except Exception as e:
                        self._detailed_log.append({
                            "event": "agent_error",
                            "agent_id": aid,
                            "agent_name": name,
                            "timestamp": datetime.now().isoformat(),
                            "error": str(e),
                        })
                        raise

                return handler

            handlers[agent_id] = await create_handler(
                agent_prompt,
                agent_name,
                agent_llm,
                agent_id,
                all_agent_names,
                agent_tools,
                agent_kb,
                agents_config,
            )

        return handlers
