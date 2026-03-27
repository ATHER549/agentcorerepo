import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agentcore.graph_langgraph.nodes import _resolve_vertex_dependencies
from agentcore.inputs.inputs import HandleInput, IntInput, MultilineInput, TableInput
from agentcore.logging import logger
from agentcore.schema.content_block import ContentBlock
from agentcore.schema.content_types import ToolContent
from agentcore.schema.data import Data
from agentcore.schema.message import Message
from agentcore.template.field.base import Output
from agentcore.custom.custom_node.node import Node
from agentcore.utils.constants import MESSAGE_SENDER_AI, MESSAGE_SENDER_NAME_AI

# Log prefix for easy grep
_LOG = "[CollaborativeAgent]"


# ---------------------------------------------------------------------------
# Shared thread data structures
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    """A single message in the shared collaborative thread."""
    sender: str
    content: str
    mentions: list[str] = field(default_factory=list)
    turn_number: int = 0
    is_done: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")


class SharedThread:
    """Shared conversation visible to all agents in the collaborative agent."""

    def __init__(self):
        self.messages: list[ChatMessage] = []

    def add_system_message(self, content: str, turn: int = 0) -> None:
        msg = ChatMessage(sender="[System]", content=content, turn_number=turn)
        self.messages.append(msg)

    def add_agent_message(
        self, sender: str, content: str, all_agent_names: list[str], turn: int = 0,
    ) -> ChatMessage:
        mentions = [
            name for name in all_agent_names
            if name != sender and f"@{name}" in content
        ]
        is_done = content.strip().upper().startswith("DONE:")
        msg = ChatMessage(
            sender=sender, content=content, mentions=mentions,
            turn_number=turn, is_done=is_done,
        )
        self.messages.append(msg)
        return msg

    def format_for_prompt(self) -> str:
        lines = []
        for msg in self.messages:
            prefix = f"[Turn {msg.turn_number}] " if msg.turn_number else ""
            lines.append(f"{prefix}{msg.sender}: {msg.content}")
        return "\n\n".join(lines)

    def get_done_message(self) -> ChatMessage | None:
        for msg in reversed(self.messages):
            if msg.is_done:
                return msg
        return None

    def recent_messages(self, n: int = 15) -> list[ChatMessage]:
        if len(self.messages) <= n:
            return list(self.messages)
        return [self.messages[0]] + self.messages[-(n - 1):]

    def dump_thread(self) -> str:
        """Return a full dump of the thread for logging."""
        lines = []
        for i, msg in enumerate(self.messages):
            done_tag = " [DONE]" if msg.is_done else ""
            mention_tag = f" @mentions={msg.mentions}" if msg.mentions else ""
            lines.append(
                f"  [{i}] Turn {msg.turn_number} | {msg.sender}{done_tag}{mention_tag}: "
                f"{msg.content[:200]}{'...' if len(msg.content) > 200 else ''}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Collaborative Agent Component
# ---------------------------------------------------------------------------

class CollaborativeAgent(Node):
    """Peer-to-peer multi-agent collaboration without a central supervisor.

    Each connected agent sees the full shared conversation thread and independently
    decides whether to SPEAK, PASS, or declare DONE. Agents communicate via
    @mentions and negotiate solutions as peers.

    **Canvas wiring:**
    1. Connect ``ChatInput`` -> ``CollaborativeAgent.Task Input``
    2. Fill the **Agents** table (one row per peer agent).
    3. Connect each output handle (e.g. *Researcher*) -> a ``Worker Node`` on canvas.
    4. Connect ``CollaborativeAgent.Final Response`` -> ``ChatOutput``.

    Agents are invoked **in parallel** each turn. The agent ends when any agent
    declares DONE, all agents PASS, or ``max_turns`` is reached.
    """

    trace_type = "agent"
    display_name = "Collaborative Agent"
    description = (
        "Peer-to-peer multi-agent collaboration. Agents communicate in a shared "
        "thread, @mention each other, and negotiate solutions without a supervisor."
    )
    icon = "bot"
    name = "CollaborativeAgent"

    inputs = [
        HandleInput(
            name="input_data",
            display_name="Task Input",
            input_types=["Message", "Data"],
            required=True,
            info="The task or question for the collaborative agent. Connect ChatInput here.",
        ),
        HandleInput(
            name="agent_llm",
            display_name="Synthesis LLM",
            input_types=["LanguageModel"],
            required=False,
            info=(
                "Optional fallback LLM used to synthesize a final answer if no agent "
                "declares DONE explicitly. If not connected, the last DONE message is used."
            ),
        ),
        MultilineInput(
            name="system_prompt",
            display_name="Agent Instructions",
            value=(
                "You are part of a collaborative team of peer agents. "
                "There is no supervisor — you communicate directly with each other "
                "via a shared conversation. Use @mentions to address specific agents. "
                "Contribute your expertise, build on others' work, and negotiate "
                "the best solution together."
            ),
            info="Shared instructions given to all agents as context.",
        ),
        TableInput(
            name="agents",
            display_name="Agents",
            info=(
                "Define the peer agents. Each row creates an output handle. "
                "Connect that handle to a Worker Node configured for that role."
            ),
            table_schema=[
                {
                    "name": "agent_name",
                    "display_name": "Agent Name",
                    "type": "str",
                    "description": "Name shown on the output handle (e.g. Researcher, Writer)",
                },
                {
                    "name": "description",
                    "display_name": "Description",
                    "type": "str",
                    "description": "What this agent specializes in (shown to other agents)",
                },
            ],
            value=[
                {"agent_name": "Agent 1", "description": "Describe this agent's expertise"},
                {"agent_name": "Agent 2", "description": "Describe this agent's expertise"},
            ],
            real_time_refresh=True,
        ),
        IntInput(
            name="max_turns",
            display_name="Max Turns",
            value=10,
            advanced=True,
            info="Maximum conversation turns before forcing completion.",
        ),
    ]

    outputs = [
        Output(
            display_name="Agent 1",
            name="Agent 1",
            method="agent_output",
            group_outputs=True,
            types=["Message"],
        ),
        Output(
            display_name="Agent 2",
            name="Agent 2",
            method="agent_output",
            group_outputs=True,
            types=["Message"],
        ),
        Output(
            display_name="Final Response",
            name="Final Response",
            method="agent_output",
            group_outputs=True,
            types=["Message"],
        ),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loop_result: Message | None = None
        self._loop_ran: bool = False

    def _pre_run_setup(self) -> None:
        self._loop_ran = False
        self._loop_result = None

    # ------------------------------------------------------------------
    # Output method — called once per output handle
    # ------------------------------------------------------------------

    async def agent_output(self) -> Message:
        """Handle each output port.

        Agent ports are stopped immediately (agents are invoked internally).
        The *Final Response* port runs the collaborative loop.
        """
        current = self._current_output

        if current != "Final Response":
            self.stop(current)
            return Message(text="")

        if not self._loop_ran:
            self._loop_result = await self._run_agent_loop()
            self._loop_ran = True

        return self._loop_result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Dynamic output handles (driven by agents table)
    # ------------------------------------------------------------------

    def update_outputs(self, frontend_node: dict, field_name: str, field_value: Any) -> dict:
        """Rebuild output handles whenever the agents table changes."""
        if field_name != "agents" or not field_value:
            return frontend_node

        outputs = []
        for row in field_value:
            if isinstance(row, dict):
                name = (row.get("agent_name") or "").strip()
                if name:
                    outputs.append(
                        Output(
                            display_name=name,
                            name=name,
                            method="agent_output",
                            group_outputs=True,
                            types=["Message"],
                        )
                    )

        outputs.append(
            Output(
                display_name="Final Response",
                name="Final Response",
                method="agent_output",
                group_outputs=True,
                types=["Message"],
            )
        )

        frontend_node["outputs"] = outputs
        return frontend_node

    # ------------------------------------------------------------------
    # Agent map from graph edges (reuses SupervisorAgent patterns)
    # ------------------------------------------------------------------

    def _get_agent_map(self) -> dict[str, str]:
        """Return {agent_display_name: target_vertex_id} from graph edges."""
        graph = getattr(self._vertex, "graph", None)
        if graph is None:
            logger.error(f"{_LOG} _vertex.graph is None — cannot build agent map")
            return {}

        my_id = self._vertex.id

        # Strategy 1: sourceHandle.name from graph.edges
        result = self._extract_agent_map_from_edges(
            getattr(graph, "edges", []), my_id,
        )
        if result:
            return result

        # Strategy 2: raw_graph_data edges
        raw_edges = (
            graph.raw_graph_data.get("edges", [])
            if hasattr(graph, "raw_graph_data") else []
        )
        if raw_edges:
            result = self._extract_agent_map_from_edges(raw_edges, my_id)
            if result:
                return result

        # Strategy 3: positional heuristic from successor_map
        result = self._build_agent_map_from_successors(graph, my_id)
        if result:
            return result

        logger.error(f"{_LOG} _get_agent_map() returned empty for {my_id}")
        return {}

    @staticmethod
    def _extract_agent_map_from_edges(edges: list, my_id: str) -> dict[str, str]:
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
        return result

    def _build_agent_map_from_successors(self, graph: Any, my_id: str) -> dict[str, str]:
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

        agent_names: list[str] = [
            (r.get("agent_name") or "").strip()
            for r in (self.agents or [])
            if isinstance(r, dict) and (r.get("agent_name") or "").strip()
        ]
        result: dict[str, str] = {}
        for i, name in enumerate(agent_names):
            if i >= len(ordered_targets):
                break
            result[name] = ordered_targets[i]
        return result

    # ------------------------------------------------------------------
    # Agent vertex invocation (adapted from SupervisorAgent._invoke_worker)
    # ------------------------------------------------------------------

    async def _invoke_agent_vertex(
        self,
        vertex_id: str,
        agent_name: str,
        thread: SharedThread,
        all_agent_names: list[str],
        agent_descriptions: dict[str, str],
    ) -> str:
        """Build a connected agent vertex with the shared thread as input."""
        vertex = self._vertex.graph.get_vertex(vertex_id)
        if vertex is None:
            logger.error(f"{_LOG} Agent vertex not found: {vertex_id}")
            return f"Agent vertex not found: {vertex_id}"

        lg_state: dict = getattr(self._vertex.graph, "_current_lg_state", {})
        state_results: dict = lg_state.get("vertices_results", {})
        resolved = _resolve_vertex_dependencies(vertex, {"vertices_results": state_results})
        if resolved:
            vertex.update_raw_params(resolved, overwrite=True)

        # Build the agent's input: thread + decision instructions
        other_agents = [n for n in all_agent_names if n != agent_name]
        mentions_str = ", ".join(f"@{n}" for n in other_agents)
        agent_desc_block = "\n".join(
            f"- **{n}**: {agent_descriptions.get(n, 'No description')}"
            for n in all_agent_names
        )

        # Use recent messages to keep prompt manageable
        recent = thread.recent_messages(15)
        if len(recent) < len(thread.messages):
            thread_text = (
                f"[... {len(thread.messages) - len(recent)} earlier messages omitted ...]\n\n"
                + "\n\n".join(
                    f"[Turn {m.turn_number}] {m.sender}: {m.content}" for m in recent
                )
            )
        else:
            thread_text = thread.format_for_prompt()

        prompt = f"""You are **{agent_name}** in a peer-to-peer collaborative team.
Your expertise: {agent_descriptions.get(agent_name, 'your role')}

{self.system_prompt or ""}

**Team members:**
{agent_desc_block}

**SHARED CONVERSATION:**
{thread_text}

**YOUR DECISION — choose exactly ONE:**
1. **CONTRIBUTE** — You have something useful to add. Write your response directly.
   - **MANDATORY**: Start your response by @mentioning the teammate you're handing off to or responding to. Example: "@Writer here's the research data you need" or "@Researcher can you look into X?"
   - Available mentions: {mentions_str}
   - You MUST include at least one @mention in every CONTRIBUTE response. This is how teammates know who should go next.
   - Build on what others have said. Don't repeat work already done.
   - Focus on YOUR expertise. Don't do other team members' jobs.
   - Completing YOUR part is a CONTRIBUTE, not a DONE. Other teammates may still need to do their part.
2. **PASS** — Reply with exactly: PASS
   - PASS if the task does NOT need your specific expertise. Not every task requires every team member.
   - PASS if your role is irrelevant to what was asked. Read the original task carefully — if it doesn't call for your skill, PASS.
   - PASS if you have nothing new or useful to add beyond what's already been said.
3. **DONE: [final answer]** — The ENTIRE TEAM's work is complete (not just yours). Write DONE: followed by the **complete** final deliverable.
   - DONE means every teammate has done their job. If anyone hasn't contributed yet, CONTRIBUTE your part instead.
   - Look at the conversation: has each team member played their role? If not, don't declare DONE.
   - DONE **must** include the full, finished work — not just "looks good" or "approved".
   - If you are reviewing/editing, DONE: must contain the **complete revised version** with all changes applied.

Reply with your contribution, PASS, or DONE: [answer]. Nothing else."""

        # Forward any uploaded files (images, documents) from the original user
        # message so agent workers can process them (e.g. vision models analysing images).
        files_from_state = lg_state.get("files") or []
        if not files_from_state and isinstance(self.input_data, Message) and self.input_data.files:
            files_from_state = self.input_data.files

        vertex.update_raw_params({"input_value": Message(text=prompt, files=files_from_state or [])}, overwrite=True)

        # Reset built state so the vertex executes fresh.
        vertex.built = False
        vertex.built_object = None
        vertex.built_result = None
        # CRITICAL: clear the cached component instance so a fresh one is
        # created with the updated params.  Without this, the AgentNode from
        # the previous turn is reused and its stale internal state (chat_history,
        # _agent_result, etc.) causes it to return the old response.
        vertex.custom_component = None

        user_id = lg_state.get("user_id")

        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(
                vertex.build(
                    user_id=user_id,
                    inputs={},
                    files=files_from_state or None,
                    event_manager=getattr(self._vertex.graph, "_event_manager", None),
                    fallback_to_env_vars=False,
                ),
                timeout=120,
            )
            result_text = self._extract_result(vertex.built_result)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                f"{_LOG} Agent {agent_name!r} responded in {duration_ms}ms | "
                f"action={'PASS' if result_text.strip().upper() == 'PASS' else 'DONE' if result_text.strip().upper().startswith('DONE:') else 'SPEAK'} | "
                f"len={len(result_text)} | preview={result_text[:200]!r}"
            )
            return result_text
        except asyncio.TimeoutError:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(
                f"{_LOG} Agent {agent_name!r} TIMED OUT after {duration_ms}ms "
                f"(limit=120s) — treating as PASS"
            )
            return "PASS"
        except Exception as e:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(
                f"{_LOG} Agent {agent_name!r} EXCEPTION after {duration_ms}ms: "
                f"{type(e).__name__}: {e} — treating as PASS"
            )
            return "PASS"

    # ------------------------------------------------------------------
    # Intelligent routing — decide which agents to involve and in what order
    # ------------------------------------------------------------------

    async def _plan_agent_order(
        self,
        task: str,
        agent_map: dict[str, str],
        agent_descriptions: dict[str, str],
    ) -> dict[str, str]:
        """Use agent_llm to pick relevant agents and order them for the task.

        Returns a reordered agent_map containing only agents the LLM deems
        relevant.  Falls back to the original map if the LLM is not connected
        or the response cannot be parsed.
        """
        llm = getattr(self, "agent_llm", None)
        if llm is None:
            return agent_map

        agents_block = "\n".join(
            f"- {name}: {agent_descriptions.get(name, 'No description')}"
            for name in agent_map
        )
        prompt = (
            f"Given the following task and available team members, decide which "
            f"team members are needed and in what order they should work.\n\n"
            f"Task: {task}\n\n"
            f"Available team members:\n{agents_block}\n\n"
            f"Reply with ONLY a JSON array of the team member names that are "
            f"relevant, in the order they should execute. Example: "
            f'["Researcher", "Writer"]\n'
            f"If only one member is needed, return just that one. "
            f"Do NOT include members whose expertise is irrelevant to the task."
        )

        try:
            response = await asyncio.wait_for(
                llm.ainvoke(prompt), timeout=15,
            )
            text = (
                response.content if hasattr(response, "content") else str(response)
            ).strip()

            # Extract JSON array from response
            match = re.search(r"\[.*?\]", text, re.DOTALL)
            if not match:
                logger.warning(f"{_LOG} _plan_agent_order: no JSON array in response — using all agents")
                return agent_map

            ordered_names: list[str] = json.loads(match.group())
            if not ordered_names or not isinstance(ordered_names, list):
                return agent_map

            # Build reordered map with only the selected agents
            ordered_map: dict[str, str] = {}
            for name in ordered_names:
                name = name.strip()
                if name in agent_map:
                    ordered_map[name] = agent_map[name]

            if not ordered_map:
                logger.warning(f"{_LOG} _plan_agent_order: no valid agents in LLM response — using all")
                return agent_map

            logger.info(
                f"{_LOG} _plan_agent_order: selected {list(ordered_map.keys())} "
                f"from {list(agent_map.keys())}"
            )
            return ordered_map

        except Exception as e:
            logger.warning(f"{_LOG} _plan_agent_order failed: {e} — using all agents")
            return agent_map

    # ------------------------------------------------------------------
    # Core collaborative loop
    # ------------------------------------------------------------------

    async def _run_agent_loop(self) -> Message:
        """Run the collaborative agent conversation loop."""
        original_task = self._extract_text(self.input_data)
        agent_map_all = self._get_agent_map()

        # Build agent descriptions lookup (needed for planning)
        agent_descriptions: dict[str, str] = {}
        for row in self.agents or []:
            if isinstance(row, dict):
                name = (row.get("agent_name") or "").strip()
                desc = (row.get("description") or "").strip()
                if name:
                    agent_descriptions[name] = desc

        # Use LLM to determine which agents are relevant and their order
        agent_map = await self._plan_agent_order(
            original_task, agent_map_all, agent_descriptions,
        )
        agent_names = list(agent_map.keys())

        logger.info(
            f"{_LOG} =====Collaborative LOOP START =====\n"
            f"  Task: {original_task[:200]!r}\n"
            f"  Agents: {agent_names}\n"
            f"  Agent map: {agent_map}\n"
            f"  Max turns: {self.max_turns}"
        )

        if not agent_names:
            logger.error(f"{_LOG} No agents connected — aborting agent")
            return Message(
                text="No agents connected. Please connect Worker Nodes to the agent handles.",
                sender=MESSAGE_SENDER_AI,
                sender_name=self.display_name,
            )

        # Build agent descriptions lookup
        agent_descriptions: dict[str, str] = {}
        for row in self.agents or []:
            if isinstance(row, dict):
                name = (row.get("agent_name") or "").strip()
                desc = (row.get("description") or "").strip()
                if name:
                    agent_descriptions[name] = desc

        # Initialize shared thread
        thread = SharedThread()
        thread.add_system_message(f"Task: {original_task}", turn=0)

        # Track consecutive PASS counts per agent
        pass_counts: dict[str, int] = {name: 0 for name in agent_names}
        max_consecutive_pass = 5

        # Track @mentions from each turn to drive next-turn invocation
        mentioned_next_turn: set[str] = set()

        # Trace display
        steps: list[ToolContent] = []

        _lg_state_ref = (
            getattr(self._vertex.graph, "_current_lg_state", {})
            if hasattr(self, "_vertex") else {}
        )
        session_id = (
            _lg_state_ref.get("session_id")
            or getattr(self.graph, "_session_id", None)
            or getattr(self.graph, "session_id", None)
        ) if hasattr(self, "graph") else None

        agent_message = Message(
            text="",
            sender=MESSAGE_SENDER_AI,
            sender_name=self.display_name or MESSAGE_SENDER_NAME_AI,
            session_id=session_id,
            properties={"icon": "bot", "state": "partial"},
            content_blocks=[ContentBlock(title="Collaborative Agent Trace", contents=[])],
        )
        agent_message = await self.send_message(agent_message)

        async def _push_update() -> None:
            nonlocal agent_message
            agent_message.content_blocks = [
                ContentBlock(title="Collaborative Agent Trace", contents=list(steps))
            ]
            agent_message = await self.send_message(agent_message)

        async def _finish(final_answer: str) -> Message:
            nonlocal agent_message
            event_manager = getattr(self, "_event_manager", None)
            msg_id = (
                str(agent_message.id)
                if hasattr(agent_message, "id") and agent_message.id else None
            )
            if event_manager and msg_id:
                words = final_answer.split(" ")
                for i, word in enumerate(words):
                    chunk = word + (" " if i < len(words) - 1 else "")
                    event_manager.on_token(data={"chunk": chunk, "id": msg_id})
                    await asyncio.sleep(0.02)

            agent_message.text = final_answer
            agent_message.properties.state = "complete"
            agent_message.content_blocks = [
                ContentBlock(title="Collaborative Agent Trace", contents=list(steps))
            ]
            return await self.send_message(agent_message)

        # ── Main conversation loop ─────────────────────────────────────
        loop_start = time.perf_counter()
        for turn in range(1, self.max_turns + 1):
            # Check if already DONE
            done_msg = thread.get_done_message()
            if done_msg:
                final_answer = self._extract_done_content(done_msg.content)
                total_ms = int((time.perf_counter() - loop_start) * 1000)
                logger.info(f"{_LOG} DONE by {done_msg.sender} | {total_ms}ms")
                return await _finish(final_answer)

            # Determine which agents are active this turn.
            # Turn 1: only the FIRST agent (best suited, from planning step).
            # Turn 2+: only @mentioned agents. Fallback to all if no mentions.
            if turn == 1:
                # Start with the best agent only — it will @mention the next
                first_name = agent_names[0]
                active_agents = {first_name: agent_map[first_name]}
            elif mentioned_next_turn:
                # Only invoke agents that were @mentioned last turn
                active_agents = {
                    name: vid for name, vid in agent_map.items()
                    if name in mentioned_next_turn
                    and pass_counts.get(name, 0) < max_consecutive_pass
                }
            else:
                # No mentions — fallback to all agents
                active_agents = {
                    name: vid for name, vid in agent_map.items()
                    if pass_counts.get(name, 0) < max_consecutive_pass
                }
            mentioned_next_turn = set()  # Reset for this turn

            if not active_agents:
                break

            # Add turn marker
            turn_content = ToolContent(
                name=f"Turn {turn}",
                tool_input={"active_agents": list(active_agents.keys())},
                output=None,
                duration=0,
                header={"title": f"**Turn {turn}** — {len(active_agents)} agents active", "icon": "bot"},
            )
            steps.append(turn_content)
            await _push_update()

            # Invoke agents SEQUENTIALLY so each agent sees what previous
            # agents contributed within the same turn.  This enables real
            # collaboration: Researcher speaks → Writer sees data → Editor
            # reviews.  The collab vertex is hidden once for the whole turn.
            t0 = time.perf_counter()
            collab_vertex = self._vertex
            collab_was_built = collab_vertex.built
            collab_vertex.built = False

            results: dict[str, str] = {}
            for name, vid in active_agents.items():
                try:
                    result = await self._invoke_agent_vertex(
                        vid, name, thread, agent_names, agent_descriptions,
                    )
                    results[name] = result
                except Exception as e:
                    logger.error(f"{_LOG} {name} exception: {type(e).__name__}: {e}")
                    results[name] = "PASS"

                # Process this agent's response IMMEDIATELY so the next
                # agent in the same turn sees it in the shared thread.
                text = results[name].strip()

                # Auto-inject @NextAgent if agent SPOKE without any @mention.
                # This makes the thread look like real back-and-forth hand-offs.
                if (
                    text.upper() != "PASS"
                    and not text.upper().startswith("DONE:")
                    and not any(f"@{n}" in text for n in agent_names if n != name)
                ):
                    idx = agent_names.index(name) if name in agent_names else -1
                    if idx >= 0 and idx + 1 < len(agent_names):
                        next_agent = agent_names[idx + 1]
                        text = f"@{next_agent} {text}"
                        results[name] = text

                if text.upper() != "PASS":
                    thread.add_agent_message(name, text, agent_names, turn=turn)

                # If an agent declares DONE, skip remaining agents in this turn.
                if text.upper().startswith("DONE:"):
                    break

            collab_vertex.built = collab_was_built

            turn_duration_ms = int((time.perf_counter() - t0) * 1000)

            someone_spoke = False
            done_found = False
            spoke_after_done = False
            done_agent = ""

            # Process results for tracking, trace display, and DONE detection.
            # Messages were already added to the thread during sequential invoke.
            # Only iterate over agents that actually ran (skipped agents after
            # early DONE won't be in results).
            for name in results:
                text = results[name].strip()

                if text.upper() == "PASS":
                    pass_counts[name] = pass_counts.get(name, 0) + 1
                    steps.append(ToolContent(
                        name=name,
                        tool_input={"action": "PASS"},
                        output="PASS",
                        duration=0,
                        header={"title": f"**{name}** — PASS", "icon": "bot"},
                    ))
                else:
                    pass_counts[name] = 0
                    someone_spoke = True
                    is_done = text.upper().startswith("DONE:")
                    action = "DONE" if is_done else "SPEAK"

                    # Find mentions — these drive next-turn invocation
                    mentions = [
                        n for n in agent_names
                        if n != name and f"@{n}" in text
                    ]

                    # Auto-mention: if agent SPOKE without @mentioning anyone,
                    # route to the next agent in the planned order.
                    if not mentions and not is_done:
                        idx = agent_names.index(name) if name in agent_names else -1
                        if idx >= 0 and idx + 1 < len(agent_names):
                            next_agent = agent_names[idx + 1]
                            mentions = [next_agent]
                            logger.info(f"{_LOG} Auto-mention: {name} → @{next_agent}")

                    mentioned_next_turn.update(mentions)

                    display_text = text[:500] + ("..." if len(text) > 500 else "")
                    mentions_str = (
                        f" (mentions: {', '.join(mentions)})" if mentions else ""
                    )
                    steps.append(ToolContent(
                        name=name,
                        tool_input={"action": action},
                        output=display_text,
                        duration=0,
                        header={
                            "title": f"**{name}**{mentions_str} — {action}",
                            "icon": "bot",
                        },
                    ))

                    if is_done:
                        done_found = True
                        done_agent = name
                    elif done_found:
                        # Agent spoke AFTER a DONE — continue loop for revision.
                        spoke_after_done = True

            # Update turn trace with duration
            turn_content.duration = turn_duration_ms
            turn_content.header = {
                "title": (
                    f"**Turn {turn}** — {len(active_agents)} agents "
                    f"({turn_duration_ms / 1000:.1f}s)"
                ),
                "icon": "bot",
            }
            await _push_update()

            if done_found:
                if spoke_after_done:
                    # Someone gave feedback after DONE — continue for revision.
                    done_found = False
                    spoke_after_done = False
                else:
                    done_msg = thread.get_done_message()
                    if done_msg:
                        final_answer = self._extract_done_content(done_msg.content)
                        total_ms = int((time.perf_counter() - loop_start) * 1000)
                        logger.info(f"{_LOG} DONE by {done_msg.sender} | turn {turn} | {total_ms}ms")
                        return await _finish(final_answer)

            if not someone_spoke:
                break

        # ── Loop ended without explicit DONE ───────────────────────────
        total_ms = int((time.perf_counter() - loop_start) * 1000)
        logger.info(f"{_LOG} Loop ended (no DONE) | {total_ms}ms | {len(thread.messages)} messages")
        return await _finish(self._synthesize_final_answer(thread, original_task))

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_done_content(text: str) -> str:
        """Extract the content after 'DONE:' prefix."""
        match = re.match(r"(?i)^DONE:\s*", text)
        if match:
            return text[match.end():].strip()
        return text

    def _synthesize_final_answer(self, thread: SharedThread, original_task: str) -> str:
        """Build a final answer from the thread when no agent declared DONE."""
        agent_messages = [
            m for m in thread.messages
            if m.sender != "[System]" and m.content.upper() != "PASS"
        ]
        if not agent_messages:
            return f"The collaborative agent could not produce a response for: {original_task}"

        if len(agent_messages) == 1:
            return agent_messages[-1].content

        return agent_messages[-1].content

    @staticmethod
    def _extract_text(value: Any) -> str:
        if isinstance(value, Message):
            return value.text or ""
        if isinstance(value, Data):
            if isinstance(value.data, dict):
                return json.dumps(value.data, indent=2)
            return str(value.data)
        if isinstance(value, dict):
            return json.dumps(value, indent=2)
        return str(value) if value else ""

    @staticmethod
    def _extract_result(built_result: Any) -> str:
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
