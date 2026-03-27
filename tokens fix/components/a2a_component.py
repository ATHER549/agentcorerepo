# TARGET PATH: src/backend/base/agentcore/components/agents/a2a_component.py
"""A2A (Agent-to-Agent) Network Hub Component.

This component implements Google's A2A protocol for multi-agent communication.
It acts as a visual hub on the canvas — users add agent names to a table, which
creates dynamic output handles that connect to A2AClient nodes.

Agents run INDEPENDENTLY using an @mention-driven conversation loop:
1. Hub picks the starting agent (smart routing or manual).
2. That agent does its work and @mentions the next agent in its response.
3. Hub reads the @mention and invokes the next agent with the full thread.
4. Loop continues until an agent says DONE: [final answer] or max turns.

Canvas wiring (no back-edges):
1. Connect ChatInput → A2A Hub.Task
2. Fill the Agents table (one row per agent name + description).
3. Connect each output handle (e.g. "Researcher") → an A2AClient node.
4. Connect A2A Hub.Final Response → ChatOutput.

Agents decide who to call next — the Hub only facilitates.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any

from agentcore.custom.custom_node.node import Node
from agentcore.graph_langgraph.nodes import _resolve_vertex_dependencies
from agentcore.io import (
    BoolInput,
    DropdownInput,
    HandleInput,
    IntInput,
    MultilineInput,
    Output,
    TableInput,
)
from agentcore.logging import logger
from agentcore.schema.content_block import ContentBlock
from agentcore.schema.content_types import ToolContent
from agentcore.schema.data import Data
from agentcore.schema.dotdict import dotdict
from agentcore.schema.message import Message
from agentcore.utils.constants import MESSAGE_SENDER_AI


class A2AAgentsComponent(Node):
    """Visual hub for Agent-to-Agent communication using Google A2A protocol.

    Add agent names in the table — each name becomes an output handle on the
    node.  Connect each handle to an A2AClient node configured with the
    corresponding local (or remote) agent.

    Agents run independently: each agent sees the shared conversation thread,
    does its part, and @mentions the next teammate.  The Hub just picks the
    first agent and then facilitates the @mention-driven loop.
    """

    trace_type = "agent"
    display_name: str = "A2A Agents"
    description: str = (
        "Visual A2A network hub. Agents communicate independently via @mentions — "
        "each agent decides who goes next.  The Hub picks the starting agent and "
        "facilitates the conversation loop."
    )
    documentation: str = "https://docs.agentcore.org/a2a-agents"
    icon = "Network"
    name = "A2AAgents"
    beta = False

    inputs = [
        # ===== Agent Names Table =====
        TableInput(
            name="agents",
            display_name="Agents",
            info=(
                "Define the agents in the A2A network. Each row creates an output handle — "
                "connect it to an A2AClient node on the canvas. "
                "Descriptions help agents understand each other's expertise."
            ),
            required=True,
            real_time_refresh=True,
            table_schema=[
                {
                    "name": "name",
                    "display_name": "Agent Name",
                    "type": "str",
                    "description": "Name shown on the output handle (e.g. Researcher, Writer)",
                },
                {
                    "name": "description",
                    "display_name": "Description",
                    "type": "str",
                    "description": "What this agent specialises in (visible to all agents)",
                },
            ],
            value=[
                {"name": "Agent 1", "description": ""},
                {"name": "Agent 2", "description": ""},
            ],
        ),
        # ===== Task Input =====
        HandleInput(
            name="input_data",
            display_name="Task Input",
            input_types=["Message", "Data"],
            required=True,
            info="The task or question to send to the starting agent. Connect ChatInput here.",
        ),
        # ===== Routing Configuration =====
        HandleInput(
            name="router_llm",
            display_name="Router LLM",
            input_types=["LanguageModel"],
            required=False,
            info="LLM used to pick the best agent to START the conversation. Optional.",
            advanced=True,
        ),
        BoolInput(
            name="smart_routing",
            display_name="Smart Routing",
            info=(
                "When enabled, the Router LLM picks the best agent to START the "
                "conversation. After that, agents self-route via @mentions."
            ),
            value=True,
            advanced=True,
        ),
        DropdownInput(
            name="starting_agent",
            display_name="Starting Agent (Manual)",
            options=[],
            value="",
            info="Manually select which agent starts. Used when Smart Routing is disabled.",
            advanced=True,
        ),
        IntInput(
            name="max_turns",
            display_name="Max Turns",
            info="Maximum number of agent-to-agent turns before the conversation ends.",
            value=10,
            advanced=True,
        ),
        MultilineInput(
            name="context",
            display_name="Additional Context",
            info="Optional additional context to include with the task.",
            value="",
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Final Response",
            name="Final Response",
            method="a2a_output",
            group_outputs=True,
            types=["Message"],
        ),
    ]

    def __init__(self, **data):
        super().__init__(**data)
        self._conversation_log: list[dict] = []
        self._detailed_log: list[dict] = []
        self._loop_ran = False
        self._loop_result: Message | None = None

    # ------------------------------------------------------------------
    # Dynamic output handles (driven by the agents table)
    # ------------------------------------------------------------------

    def update_outputs(self, frontend_node: dict, field_name: str, field_value: Any) -> dict:
        """Rebuild output handles whenever the agents table changes."""
        if field_name != "agents" or not field_value:
            return frontend_node

        outputs = []
        for row in field_value:
            if isinstance(row, dict):
                name = (row.get("name") or "").strip()
                if name:
                    outputs.append(
                        Output(
                            display_name=name,
                            name=name,
                            method="a2a_output",
                            group_outputs=True,
                            types=["Message"],
                        )
                    )

        outputs.append(
            Output(
                display_name="Final Response",
                name="Final Response",
                method="a2a_output",
                group_outputs=True,
                types=["Message"],
            )
        )
        frontend_node["outputs"] = outputs
        return frontend_node

    async def update_build_config(
        self, build_config: dotdict, field_value: Any, field_name: str | None = None
    ) -> dotdict:
        """Update the starting_agent dropdown when the agents table changes."""
        if field_name == "agents":
            agent_defs = field_value if isinstance(field_value, list) else []
            agent_names = [
                (row.get("name") or "").strip()
                for row in agent_defs
                if isinstance(row, dict) and (row.get("name") or "").strip()
            ]

            if "starting_agent" in build_config:
                build_config["starting_agent"]["options"] = agent_names if agent_names else []
                current_value = build_config["starting_agent"].get("value", "")
                if current_value not in agent_names:
                    build_config["starting_agent"]["value"] = agent_names[0] if agent_names else ""

        return build_config

    # ------------------------------------------------------------------
    # Output method (Supervisor pattern)
    # ------------------------------------------------------------------

    async def a2a_output(self) -> Message:
        """Handle each output port.

        Agent-name ports are stopped immediately (agents are invoked internally).
        The *Final Response* port runs the A2A workflow and returns the result.
        """
        current = self._current_output
        if current != "Final Response":
            self.stop(current)
            return Message(text="")

        if not self._loop_ran:
            self._loop_result = await self._run_a2a_workflow()
            self._loop_ran = True
        return self._loop_result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _get_agent_names(self) -> list[str]:
        """Get agent names from the table."""
        agents = getattr(self, "agents", [])
        if not isinstance(agents, list):
            return []
        return [
            (row.get("name") or "").strip()
            for row in agents
            if isinstance(row, dict) and (row.get("name") or "").strip()
        ]

    def _get_agent_descriptions(self) -> dict[str, str]:
        """Get {agent_name: description} from the agents table."""
        agents = getattr(self, "agents", [])
        if not isinstance(agents, list):
            return {}
        result: dict[str, str] = {}
        for row in agents:
            if isinstance(row, dict):
                name = (row.get("name") or "").strip()
                desc = (row.get("description") or "").strip()
                if name and desc:
                    result[name] = desc
        return result

    # ------------------------------------------------------------------
    # Worker map: resolve canvas connections (agent name → vertex ID)
    # ------------------------------------------------------------------

    def _get_worker_map(self) -> dict[str, str]:
        """Return {agent_display_name: target_vertex_id} from graph edges."""
        graph = getattr(self._vertex, "graph", None)
        if graph is None:
            logger.error("[A2AHub] _vertex.graph is None — cannot build worker map")
            return {}

        my_id = self._vertex.id

        result = self._extract_worker_map_from_edges(
            getattr(graph, "edges", []), my_id, strategy="graph.edges"
        )
        if result:
            return result

        raw_edges = graph.raw_graph_data.get("edges", []) if hasattr(graph, "raw_graph_data") else []
        if raw_edges:
            result = self._extract_worker_map_from_edges(raw_edges, my_id, strategy="raw_graph_data")
            if result:
                return result

        result = self._build_worker_map_from_successors(graph, my_id)
        if result:
            logger.warning("[A2AHub] Using positional heuristic (sourceHandle.name missing).")
            return result

        logger.error(
            f"[A2AHub] _get_worker_map() returned empty.\n"
            f"  hub vertex id: {my_id!r}\n"
            f"  agents table : {self._get_agent_names()}"
        )
        return {}

    @staticmethod
    def _extract_worker_map_from_edges(
        edges: list, my_id: str, *, strategy: str
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for edge in edges:
            if not isinstance(edge, dict) or edge.get("source") != my_id:
                continue
            target = edge.get("target", "")
            if not target:
                continue
            sh = edge.get("data", {}).get("sourceHandle", {})
            if isinstance(sh, str):
                try:
                    sh = json.loads(sh)
                except Exception:
                    sh = {}
            name = (sh.get("name") or "") if isinstance(sh, dict) else ""
            if name and name != "Final Response":
                result[name] = target
        if result:
            logger.debug(f"[A2AHub] worker map via {strategy}: {list(result.keys())}")
        return result

    def _build_worker_map_from_successors(self, graph: Any, my_id: str) -> dict[str, str]:
        ordered_targets: list[str] = []
        seen: set[str] = set()
        for edge in getattr(graph, "edges", []):
            if not isinstance(edge, dict) or edge.get("source") != my_id:
                continue
            target = edge.get("target", "")
            if not target or target in seen:
                continue
            child = graph.get_vertex(target)
            if child is None or getattr(child, "is_interface_component", False):
                continue
            ordered_targets.append(target)
            seen.add(target)

        agent_names = self._get_agent_names()
        result: dict[str, str] = {}
        for i, name in enumerate(agent_names):
            if i >= len(ordered_targets):
                break
            result[name] = ordered_targets[i]
        return result

    # ------------------------------------------------------------------
    # Worker invocation (invoke connected A2AClient vertex directly)
    # ------------------------------------------------------------------

    async def _invoke_worker(self, vertex_id: str, task: str, *, _retry: int = 0) -> str:
        """Build a connected A2AClient vertex with the given task and return result text.

        Retries once on transient network errors (ReadError, ConnectError, etc.).
        """
        vertex = self._vertex.graph.get_vertex(vertex_id)
        if vertex is None:
            return "PASS"

        lg_state: dict = getattr(self._vertex.graph, "_current_lg_state", {})
        state_results: dict = lg_state.get("vertices_results", {})

        resolved = _resolve_vertex_dependencies(vertex, {"vertices_results": state_results})
        if resolved:
            vertex.update_raw_params(resolved, overwrite=True)

        # Forward any uploaded files (images, documents) from the original user
        # message so workers can process them (e.g. vision models analysing images).
        files_from_state = lg_state.get("files") or []
        if not files_from_state and isinstance(self.input_data, Message) and self.input_data.files:
            files_from_state = self.input_data.files

        # Override the task input, preserving any uploaded files.
        task_msg = Message(text=task, files=files_from_state or [])
        if "input_message" in getattr(vertex, "template", {}):
            vertex.update_raw_params({"input_message": task_msg}, overwrite=True)
        else:
            vertex.update_raw_params({"input_value": task_msg}, overwrite=True)

        # Reset built state so the vertex executes fresh
        vertex.built = False
        vertex.built_object = None
        vertex.built_result = None

        # CRITICAL: clear cached component instance so a fresh one is created.
        # Without this, stale internal state (_last_send_result, etc.) causes
        # the component to return old/empty responses.
        # Pattern from collaborative_agent.py line 456.
        vertex.custom_component = None

        user_id = lg_state.get("user_id")

        # Temporarily hide this hub vertex from the worker's _resolve_params()
        hub_vertex = self._vertex
        hub_was_built = hub_vertex.built
        hub_vertex.built = False
        try:
            # Pass event_manager=None so the worker doesn't display its own
            # errors in the chat UI — the Hub handles errors via retry + PASS.
            await asyncio.wait_for(
                vertex.build(
                    user_id=user_id,
                    inputs={},
                    files=files_from_state or None,
                    event_manager=None,
                    fallback_to_env_vars=False,
                ),
                timeout=180,
            )
            return self._extract_result(vertex.built_result)
        except asyncio.TimeoutError:
            logger.error(f"[A2AHub] Worker {vertex_id} timed out after 180s")
            return "PASS"
        except Exception as e:
            err_name = type(e).__name__
            # Retry once on transient network errors (ReadError, ConnectError, etc.)
            if _retry < 2 and err_name in ("ReadError", "ConnectError", "RemoteProtocolError"):
                logger.warning(f"[A2AHub] Worker {vertex_id} got {err_name}, retrying in 2s...")
                await asyncio.sleep(2)
                hub_vertex.built = hub_was_built
                return await self._invoke_worker(vertex_id, task, _retry=_retry + 1)
            logger.error(f"[A2AHub] Worker {vertex_id} raised: {err_name}: {e}")
            return "PASS"
        finally:
            hub_vertex.built = hub_was_built

    @staticmethod
    def _extract_result(built_result: Any) -> str:
        """Extract plain text from a vertex's built_result."""
        if built_result is None:
            return ""
        if isinstance(built_result, Message):
            return built_result.text or ""
        if isinstance(built_result, Data):
            return str(built_result.data)
        if isinstance(built_result, dict):
            for v in built_result.values():
                if isinstance(v, Message) and v.text:
                    return v.text
            for v in built_result.values():
                if isinstance(v, Data):
                    return str(v.data)
            for v in built_result.values():
                if v:
                    return str(v)
        return str(built_result)

    # ------------------------------------------------------------------
    # @mention helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_mentions(text: str, agent_names: list[str], sender: str) -> list[str]:
        """Extract @AgentName mentions from response text."""
        return [n for n in agent_names if n != sender and f"@{n}" in text]

    def _format_thread_for_agent(
        self,
        thread: list[dict],
        agent_name: str,
        all_agents: list[str],
        task: str,
    ) -> str:
        """Build the prompt sent to an agent — thread context + @mention instructions."""
        descriptions = self._get_agent_descriptions()
        other_agents = [n for n in all_agents if n != agent_name]
        mentions_str = ", ".join(f"@{n}" for n in other_agents)
        agent_desc = "\n".join(
            f"- {n}: {descriptions.get(n, 'No description')}" for n in all_agents
        )

        # Last 15 messages to keep prompt manageable
        recent = thread[-15:] if len(thread) > 15 else thread
        if recent:
            thread_text = "\n\n".join(
                f"[Turn {msg['turn']}] {msg['sender']}: {msg['content']}"
                for msg in recent
            )
        else:
            thread_text = "(No conversation yet — you are the first agent to respond)"

        return (
            f"You are {agent_name} in a multi-agent A2A network.\n"
            f"Your expertise: {descriptions.get(agent_name, 'your role')}\n\n"
            f"Team members:\n{agent_desc}\n\n"
            f"Conversation so far:\n{thread_text}\n\n"
            f"Original Task: {task}\n\n"
            f"Choose ONE:\n"
            f"1. CONTRIBUTE + @mention — Do your part, then @mention the next agent "
            f"whose expertise is needed to fulfil the original task. "
            f"Read the task carefully — if it asks for research, writing, AND review, "
            f"make sure each step is handled by the right agent. Available: {mentions_str}\n"
            f"2. DONE: [final answer] — Every step requested in the original task is "
            f"complete. Write DONE: followed by the final deliverable.\n"
            f"3. PASS — Your skill isn't needed. Reply with exactly: PASS\n\n"
            f"Use DONE only when ALL steps in the original task are finished. "
            f"If the task asks for multiple steps and some are still pending, "
            f"@mention the agent who should handle the next step."
        )

    # ------------------------------------------------------------------
    # Smart routing — pick FIRST agent only
    # ------------------------------------------------------------------

    async def _select_first_agent(self, agent_names: list[str], task: str) -> str:
        """Use the router LLM to pick the best agent to START the conversation."""
        router_llm = getattr(self, "router_llm", None)
        if not router_llm:
            return agent_names[0]

        descriptions = self._get_agent_descriptions()
        agent_lines = "\n".join(
            f"- {name}: {descriptions[name]}" if name in descriptions else f"- {name}"
            for name in agent_names
        )

        routing_prompt = (
            f"You are a task router. Pick the ONE agent best suited to START this task.\n"
            f"After the first agent, agents will @mention each other to continue.\n\n"
            f"Available Agents:\n{agent_lines}\n\n"
            f"Task: {task}\n\n"
            f"Respond with ONLY the agent name. Nothing else."
        )

        try:
            if hasattr(router_llm, "ainvoke"):
                response = await router_llm.ainvoke(routing_prompt)
            else:
                response = router_llm.invoke(routing_prompt)

            selected = response.content.strip() if hasattr(response, "content") else str(response).strip()

            for name in agent_names:
                if name.lower() == selected.lower():
                    logger.info(f"[A2AHub] Smart routing selected starting agent: {name}")
                    return name

            for name in agent_names:
                if selected.lower() in name.lower() or name.lower() in selected.lower():
                    logger.info(f"[A2AHub] Smart routing partial match: {name}")
                    return name

            logger.warning(f"[A2AHub] Could not match '{selected}', using first agent")
        except Exception as e:
            logger.warning(f"[A2AHub] Smart routing failed: {e}, using first agent")

        return agent_names[0]

    # ------------------------------------------------------------------
    # Main workflow — @mention-driven agentic loop
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(value: Any) -> str:
        """Convert any input type to a plain string."""
        if isinstance(value, Message):
            return value.text or ""
        if isinstance(value, Data):
            if isinstance(value.data, dict):
                return json.dumps(value.data, indent=2)
            return str(value.data)
        if isinstance(value, dict):
            return json.dumps(value, indent=2)
        return str(value) if value else ""

    async def _run_a2a_workflow(self) -> Message:
        """Run the @mention-driven agentic conversation loop.

        1. Pick starting agent (smart routing or manual).
        2. Invoke agent → agent responds with @mention of next agent.
        3. Read @mentions → invoke mentioned agent with full thread.
        4. Repeat until DONE: or max turns.
        """
        agent_names = self._get_agent_names()
        if not agent_names:
            raise ValueError("No agents defined in the A2A network table")

        worker_map = self._get_worker_map()

        task_text = self._extract_text(self.input_data)
        if not task_text:
            raise ValueError("No task input provided")

        context = getattr(self, "context", "") or ""
        task_with_context = f"Context: {context}\n\nTask: {task_text}" if context else task_text

        max_turns = getattr(self, "max_turns", 10) or 10

        self._detailed_log = [{
            "event": "workflow_start",
            "timestamp": datetime.now().isoformat(),
            "agents": agent_names,
            "connected_agents": list(worker_map.keys()),
            "task": task_text,
        }]

        # ── Live trace setup ──
        trace_steps: list[ToolContent] = []
        session_id = ""
        if hasattr(self, "_vertex") and hasattr(self._vertex, "graph"):
            _lg = getattr(self._vertex.graph, "_current_lg_state", {})
            session_id = (
                _lg.get("session_id", "")
                or getattr(self._vertex.graph, "session_id", "")
                or ""
            )

        agent_message = Message(
            text="",
            sender=MESSAGE_SENDER_AI,
            sender_name="A2A Agents",
            session_id=session_id,
            properties={"icon": "Network", "state": "partial"},
            content_blocks=[ContentBlock(title="A2A Execution Trace", contents=[])],
        )
        agent_message = await self.send_message(agent_message)

        async def _push_trace() -> None:
            nonlocal agent_message
            agent_message.content_blocks = [
                ContentBlock(title="A2A Execution Trace", contents=list(trace_steps))
            ]
            agent_message = await self.send_message(agent_message)

        try:
            # ── Pick starting agent ──
            smart_routing_enabled = getattr(self, "smart_routing", True)
            if smart_routing_enabled:
                routing_step = ToolContent(
                    name="Smart Routing",
                    output=None,
                    header={"title": "Picking starting agent...", "icon": "Network"},
                )
                trace_steps.append(routing_step)
                await _push_trace()

                first_agent = await self._select_first_agent(agent_names, task_with_context)

                routing_step.output = f"Starting with: **{first_agent}**"
                routing_step.header = {"title": f"Start → **{first_agent}**", "icon": "Network"}
                await _push_trace()
            else:
                first_agent = getattr(self, "starting_agent", "") or agent_names[0]

            # Verify starting agent is connected
            if first_agent not in worker_map:
                connected = ", ".join(worker_map.keys()) if worker_map else "none"
                raise ValueError(
                    f"Agent '{first_agent}' is not connected on the canvas. "
                    f"Connected: {connected}"
                )

            self._detailed_log.append({
                "event": "starting_agent",
                "timestamp": datetime.now().isoformat(),
                "agent": first_agent,
            })

            # ── Agentic conversation loop ──
            thread: list[dict] = []
            self._conversation_log = []
            mentioned_next: set[str] = {first_agent}
            pass_counts: dict[str, int] = {n: 0 for n in agent_names}
            total_start = time.time()
            final_answer = ""

            # Hide hub vertex once for the entire loop
            hub_vertex = self._vertex
            hub_was_built = hub_vertex.built
            hub_vertex.built = False

            try:
                for turn in range(1, max_turns + 1):
                    # Only @mentioned agents run this turn
                    active = [
                        n for n in agent_names
                        if n in mentioned_next
                        and n in worker_map
                        and pass_counts.get(n, 0) < 5
                    ]
                    if not active:
                        break

                    mentioned_next = set()

                    for agent_name in active:
                        # Build prompt with full thread context
                        agent_input = self._format_thread_for_agent(
                            thread, agent_name, agent_names, task_with_context,
                        )

                        # Trace: calling agent
                        calling_step = ToolContent(
                            name=agent_name,
                            output=None,
                            header={"title": f"Calling {agent_name} via A2A...", "icon": "bot"},
                        )
                        trace_steps.append(calling_step)
                        await _push_trace()

                        step_start = time.time()
                        result = await self._invoke_worker(worker_map[agent_name], agent_input)
                        result = result.strip()
                        step_elapsed = time.time() - step_start

                        # Add to thread
                        thread.append({"sender": agent_name, "content": result, "turn": turn})

                        # Log exchange
                        self._conversation_log.append({
                            "sender": agent_name,
                            "content": result,
                            "turn": turn,
                            "timestamp": datetime.now().isoformat(),
                        })

                        # Check DONE
                        if result.upper().startswith("DONE:"):
                            final_answer = result[5:].strip()

                            calling_step.output = final_answer[:300] + "..." if len(final_answer) > 300 else final_answer
                            calling_step.header = {
                                "title": f"**{agent_name}** — DONE ({step_elapsed:.1f}s)",
                                "icon": "bot",
                            }
                            await _push_trace()

                            self._detailed_log.append({
                                "event": "agent_done",
                                "timestamp": datetime.now().isoformat(),
                                "agent": agent_name,
                                "turn": turn,
                            })
                            break  # exit inner loop

                        # Check PASS
                        if result.upper() == "PASS":
                            pass_counts[agent_name] = pass_counts.get(agent_name, 0) + 1
                            calling_step.output = "PASS"
                            calling_step.header = {
                                "title": f"**{agent_name}** — PASS ({step_elapsed:.1f}s)",
                                "icon": "bot",
                            }
                            await _push_trace()
                            continue

                        # Agent contributed — reset pass count
                        pass_counts[agent_name] = 0

                        # Extract @mentions → drive next turn
                        mentions = self._extract_mentions(result, agent_names, agent_name)

                        # Auto-mention fallback: if agent forgot @mention, route to next in table
                        if not mentions:
                            idx = agent_names.index(agent_name) if agent_name in agent_names else -1
                            if idx >= 0 and idx + 1 < len(agent_names):
                                next_agent = agent_names[idx + 1]
                                mentions = [next_agent]
                                logger.info(f"[A2AHub] Auto-mention: {agent_name} → @{next_agent}")

                        mentioned_next.update(mentions)

                        # Update trace
                        mentions_display = f" → @{', @'.join(mentions)}" if mentions else ""
                        result_preview = result[:300] + "..." if len(result) > 300 else result
                        calling_step.output = result_preview
                        calling_step.header = {
                            "title": f"**{agent_name}**{mentions_display} ({step_elapsed:.1f}s)",
                            "icon": "bot",
                        }
                        await _push_trace()

                    # If DONE was found, exit outer loop
                    if final_answer:
                        break

            finally:
                hub_vertex.built = hub_was_built

            total_elapsed = time.time() - total_start

            # If no DONE, use last non-PASS response
            if not final_answer:
                final_answer = next(
                    (m["content"] for m in reversed(thread)
                     if m["content"].upper() != "PASS"
                     and not m["content"].upper().startswith("DONE:")),
                    "No response from agents",
                )

            # ── Summary trace ──
            agents_called = list(dict.fromkeys(m["sender"] for m in thread))
            summary_step = ToolContent(
                name="A2A Network",
                output=f"{' → '.join(agents_called)} — {total_elapsed:.1f}s",
                header={
                    "title": f"A2A Complete — {len(agents_called)} agents, {total_elapsed:.1f}s",
                    "icon": "Network",
                },
            )
            trace_steps.append(summary_step)

            self._detailed_log.append({
                "event": "workflow_complete",
                "timestamp": datetime.now().isoformat(),
                "agents_called": agents_called,
                "turns": len(set(m["turn"] for m in thread)),
                "elapsed_seconds": total_elapsed,
            })

            agent_message.text = final_answer
            agent_message.properties.state = "complete"
            agent_message.content_blocks = [
                ContentBlock(title="A2A Execution Trace", contents=list(trace_steps))
            ]
            return await self.send_message(agent_message)

        except Exception as e:
            error_step = ToolContent(
                name="Error",
                output=str(e),
                header={"title": f"A2A Error: {type(e).__name__}", "icon": "Network"},
            )
            trace_steps.append(error_step)
            agent_message.properties.state = "complete"
            agent_message.content_blocks = [
                ContentBlock(title="A2A Execution Trace", contents=list(trace_steps))
            ]
            await self.send_message(agent_message)

            self._detailed_log.append({
                "event": "workflow_error",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            })
            logger.error(f"[A2AHub] Execution error: {e}")
            raise

