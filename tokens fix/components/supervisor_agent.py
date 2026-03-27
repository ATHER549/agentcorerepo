import asyncio
import json
import time
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


class SupervisorAgent(Node):
    """Multi-agent supervisor that iteratively orchestrates specialist worker agents.

    The supervisor receives a task, delegates sub-tasks to connected worker AgentNodes
    (up to ``max_hops`` times), accumulates their results, and synthesises a final answer.

    **Canvas wiring (no back-edges):**
    1. Connect ``ChatInput`` → ``SupervisorAgent.Task Input``
    2. Fill the **Workers** table (one row per worker agent).
    3. Connect each output handle (e.g. *Researcher*) → the matching ``AgentNode.input_value``.
    4. Connect ``SupervisorAgent.Final Response`` → ``ChatOutput``.

    Workers are invoked **internally** — the supervisor calls each worker vertex directly
    and reads its result, so no back-edges are needed.
    """

    trace_type = "agent"
    display_name = "Supervisor Agent"
    description = (
        "Iterative multi-agent supervisor. Delegates tasks to specialist worker agents "
        "and synthesises a final answer. No back-edges needed."
    )
    icon = "bot"
    name = "SupervisorAgent"

    inputs = [
        HandleInput(
            name="input_data",
            display_name="Task Input",
            input_types=["Message", "Data"],
            required=True,
            info="The task or question to orchestrate. Connect ChatInput here.",
        ),
        HandleInput(
            name="supervisor_llm",
            display_name="Supervisor LLM",
            input_types=["LanguageModel"],
            required=True,
            info="Language model that makes routing and synthesis decisions.",
        ),
        MultilineInput(
            name="system_prompt",
            display_name="Supervisor Instructions",
            value=(
                "You are a supervisor orchestrating a team of specialised agents. "
                "Analyse the user's request and delegate only to the workers that are "
                "relevant for that specific task. Do NOT call a worker unless its "
                "description matches what the task requires. "
                "Once sufficient information has been gathered, synthesise a clear "
                "final answer and set next to FINISH."
            ),
            info="Instructions that define the supervisor's role and strategy.",
        ),
        TableInput(
            name="workers",
            display_name="Workers",
            info=(
                "Define the worker agents. Each row creates an output handle. "
                "Connect that handle to an AgentNode configured for that role."
            ),
            table_schema=[
                {
                    "name": "worker_name",
                    "display_name": "Worker Name",
                    "type": "str",
                    "description": "Name shown on the output handle (e.g. Researcher, Coder)",
                },
                {
                    "name": "description",
                    "display_name": "Description",
                    "type": "str",
                    "description": "What this worker specialises in (used in the LLM prompt)",
                },
            ],
            value=[
                {"worker_name": "Worker 1", "description": "Describe what this worker does"},
                {"worker_name": "Worker 2", "description": "Describe what this worker does"},
            ],
            real_time_refresh=True,
        ),
        IntInput(
            name="max_hops",
            display_name="Max Hops",
            value=5,
            advanced=True,
            info="Maximum number of worker calls before the supervisor must produce a final answer.",
        ),
    ]

    outputs = [
        Output(
            display_name="Worker 1",
            name="Worker 1",
            method="supervisor_output",
            group_outputs=True,
            types=["Message"],
        ),
        Output(
            display_name="Worker 2",
            name="Worker 2",
            method="supervisor_output",
            group_outputs=True,
            types=["Message"],
        ),
        Output(
            display_name="Final Response",
            name="Final Response",
            method="supervisor_output",
            group_outputs=True,
            types=["Message"],
        ),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loop_result: Message | None = None
        self._loop_ran: bool = False

    def _pre_run_setup(self) -> None:
        """Reset per-run cache before each build cycle.

        Called by _build_results() → _pre_run_setup_if_needed() at the start
        of every vertex build, even when the component instance is reused across
        multiple runs (custom_component caching in vertex_wrapper.py).
        Without this reset _loop_ran would stay True and subsequent runs would
        return the stale first-run Message immediately.
        """
        self._loop_ran = False
        self._loop_result = None

    # ------------------------------------------------------------------
    # Output method — called once per output handle by the framework
    # ------------------------------------------------------------------

    async def supervisor_output(self) -> Message:
        """Handle each output port.

        Worker ports are stopped immediately (workers are invoked internally).
        The *Final Response* port runs the full supervisor loop and returns the
        synthesised answer.
        """
        current = self._current_output

        if current != "Final Response":
            # Stop this branch — we invoke the worker vertex directly inside the loop.
            self.stop(current)
            return Message(text="")

        # Run the internal loop once; cache result so subsequent handle evaluations
        # (if any) return the same object without re-running the loop.
        if not self._loop_ran:
            self._loop_result = await self._run_supervisor_loop()
            self._loop_ran = True

        return self._loop_result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Core async loop — mirrors process_agent_events() pattern
    # ------------------------------------------------------------------

    async def _run_supervisor_loop(self) -> Message:
        """Orchestrate workers using plan-first execution.

        Strategy:
        1. Ask the LLM to create a complete execution plan upfront:
              [{"worker": "calculater_tool", "task": "Compute 1247 + 893"},
               {"worker": "summarize",       "task": "Summarize the result"}]
           Each worker receives ONLY its own scoped subtask — not the full user query.
        2. Execute the plan steps in order, injecting previous outputs as context.
        3. Return the last successful worker's result directly (no re-synthesis).

        Fallback: if the LLM cannot produce a valid plan (parse error / empty plan),
        fall back to hop-by-hop routing where the LLM decides one step at a time.
        """
        original_task = self._extract_text(self.input_data)
        worker_map = self._get_worker_map()          # {display_name: vertex_id}
        history: list[dict[str, str]] = []
        steps: list[ToolContent] = []

        # ── Initial message ────────────────────────────────────────────
        # In the LangGraph execution path arun() is never called, so
        # graph.session_id is not set.  Read from _current_lg_state (populated
        # by node_function just before build()) and fall back to graph attrs.
        _lg_state_ref = getattr(self._vertex.graph, "_current_lg_state", {}) if hasattr(self, "_vertex") else {}
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
            content_blocks=[ContentBlock(title="Supervisor Execution Trace", contents=[])],
        )
        agent_message = await self.send_message(agent_message)

        async def _push_update() -> None:
            nonlocal agent_message
            agent_message.content_blocks = [
                ContentBlock(title="Supervisor Execution Trace", contents=list(steps))
            ]
            agent_message = await self.send_message(agent_message)

        async def _finish(final_answer: str) -> Message:
            """Finalise the supervisor run.

            Streams the final answer into the SAME trace bubble (agent_message)
            so there is only one Supervisor Agent block in the chat — identical
            to how AgentNode shows tool steps + final text in one bubble.

            Pattern (mirrors AgentNode / handle_on_chain_stream):
            1. Stream tokens directly via event_manager.on_token() into
               agent_message.id — no extra DB writes during streaming.
            2. One final send_message() updates the DB record with the complete
               text, final content_blocks, and "complete" state.
            """
            nonlocal agent_message

            # ── 1. Stream tokens into the existing trace bubble ──────────────────────
            # agent_message.id is already set (from the initial send_message at the top
            # of _run_supervisor_loop and every _push_update call). We reuse that id so
            # tokens stream into the SAME bubble — no second "Message empty." block.
            event_manager = getattr(self, "_event_manager", None)
            msg_id = str(agent_message.id) if hasattr(agent_message, "id") and agent_message.id else None
            logger.info(
                f"[SupervisorAgent] _finish: event_manager={bool(event_manager)}, "
                f"msg_id={msg_id}, answer_len={len(final_answer)}"
            )
            if event_manager and msg_id:
                words = final_answer.split(" ")
                for i, word in enumerate(words):
                    chunk = word + (" " if i < len(words) - 1 else "")
                    event_manager.on_token(data={"chunk": chunk, "id": msg_id})
                    await asyncio.sleep(0.02)  # 20 ms per word — lets SSE flush each token

            # ── 2. Final DB write: complete text + trace accordion + "complete" state ─
            agent_message.text = final_answer
            agent_message.properties.state = "complete"
            agent_message.content_blocks = [
                ContentBlock(title="Supervisor Execution Trace", contents=list(steps))
            ]
            return await self.send_message(agent_message)

        async def _invoke_step(worker_name: str, task: str, step_label: str) -> str:
            """Invoke one worker step, update live bubble, return result text."""
            worker_id = worker_map.get(worker_name)
            if not worker_id:
                logger.warning(
                    f"[SupervisorAgent] Worker '{worker_name}' not connected — skipping."
                )
                return f"Worker '{worker_name}' is not connected."

            logger.info(
                f"[SupervisorAgent] {step_label}: invoking '{worker_name}' "
                f"| task dispatched → {task!r}"
            )
            calling_content = ToolContent(
                name=worker_name,
                tool_input={"task": task},
                output=None,
                duration=0,
                header={"title": f"Calling **{worker_name}**", "icon": "bot"},
            )
            steps.append(calling_content)
            await _push_update()

            # Inject outputs from previous workers as context
            if history:
                context_block = "\n\n".join(
                    f"--- Output from {h['worker']} ---\n{h['result']}"
                    for h in history
                )
                full_task = (
                    f"{task}\n\n"
                    f"=== Context / outputs from previous workers ===\n"
                    f"{context_block}"
                )
            else:
                full_task = task

            t0 = time.perf_counter()
            result = await self._invoke_worker(worker_id, full_task)
            duration_ms = int((time.perf_counter() - t0) * 1000)

            calling_content.output = result
            calling_content.duration = duration_ms
            calling_content.header = {
                "title": f"**{worker_name}** finished ({duration_ms / 1000:.1f}s)",
                "icon": "bot",
            }

            # Nest the worker's tool steps (ToolContent items from its Agent Steps
            # content_block) inside calling_content.children so they appear
            # indented under the worker's trace entry in the Supervisor bubble.
            w_vertex = self._vertex.graph.get_vertex(worker_id)
            w_built = getattr(w_vertex, "built_result", None) if w_vertex else None
            # built_result can be a bare Message or a dict {"output_name": Message}
            if isinstance(w_built, dict):
                w_msgs = [v for v in w_built.values() if isinstance(v, Message)]
            elif isinstance(w_built, Message):
                w_msgs = [w_built]
            else:
                w_msgs = []
            for w_msg in w_msgs:
                for cb in (w_msg.content_blocks or []):
                    for item in (cb.contents or []):
                        if isinstance(item, ToolContent):
                            calling_content.children.append(item)

            await _push_update()
            return result

        # ── PRIMARY PATH: plan-first execution ────────────────────────
        # Ask the LLM to break the user's query into an ordered list of
        # (worker, scoped_task) pairs BEFORE invoking any worker.
        # This guarantees each worker receives ONLY its own subtask.
        plan = await self._plan_execution(original_task, worker_map)

        if plan:
            plan_summary = " → ".join(
                f"{s['worker']}({s['task'][:60]}{'…' if len(s['task']) > 60 else ''})"
                for s in plan
            )
            logger.info(f"[SupervisorAgent] Execution plan: {plan_summary}")
            errored_workers: set[str] = set()

            for i, step in enumerate(plan[: self.max_hops]):
                worker_name = step["worker"]
                task = step["task"]

                if worker_name in errored_workers:
                    logger.warning(
                        f"[SupervisorAgent] Skipping errored worker '{worker_name}' in plan."
                    )
                    continue

                result = await _invoke_step(
                    worker_name, task, f"Plan step {i + 1}/{len(plan)}"
                )

                _looks_like_error = (
                    result.startswith("Worker error:")
                    or result.startswith("Error:")
                    or "not found" in result.lower()
                )
                if _looks_like_error:
                    errored_workers.add(worker_name)

                history.append({"worker": worker_name, "task": task, "result": result})
                logger.info(f"[SupervisorAgent] Plan step {i + 1}: {worker_name} done")

            final_answer = self._last_successful_result(history, errored_workers) or original_task
            return await _finish(final_answer)

        # ── FALLBACK: hop-by-hop routing ───────────────────────────────
        # Plan generation failed (LLM error / parse error / empty plan).
        # Fall back to asking the LLM one step at a time, which is less
        # precise about task scoping but always produces a result.
        logger.warning(
            "[SupervisorAgent] Plan generation failed — falling back to hop-by-hop routing."
        )
        called_workers: set[str] = set()
        errored_workers_hbh: set[str] = set()
        last_called: str | None = None

        for hop in range(self.max_hops):
            decision = await self._get_supervisor_decision(
                original_task, history, worker_map,
                called_workers=called_workers,
                errored_workers=errored_workers_hbh,
            )

            if decision["next"] == "FINISH":
                if history:
                    final_answer = self._last_successful_result(history, errored_workers_hbh)
                else:
                    final_answer = decision.get("final_answer") or original_task
                return await _finish(final_answer)

            worker_name = decision["next"]

            # Guard 1: errored worker — never retry
            if worker_name in errored_workers_hbh:
                logger.warning(
                    f"[SupervisorAgent] LLM chose previously-errored worker "
                    f"'{worker_name}' — returning last successful result."
                )
                final_answer = self._last_successful_result(history, errored_workers_hbh)
                return await _finish(final_answer)

            # Guard 2: same worker twice in a row
            if worker_name == last_called:
                logger.warning(
                    f"[SupervisorAgent] LLM chose '{worker_name}' consecutively "
                    f"(hop {hop + 1}) — returning last successful result."
                )
                final_answer = self._last_successful_result(history, errored_workers_hbh)
                return await _finish(final_answer)

            task = decision.get("task") or original_task
            result = await _invoke_step(worker_name, task, f"Hop {hop + 1}/{self.max_hops}")

            if result.startswith(f"Worker '{worker_name}' is not connected"):
                return await _finish(result)

            called_workers.add(worker_name)
            last_called = worker_name
            _looks_like_error = (
                result.startswith("Worker error:")
                or result.startswith("Error:")
                or "not found" in result.lower()
            )
            if _looks_like_error:
                errored_workers_hbh.add(worker_name)
                logger.info(
                    f"[SupervisorAgent] hop {hop + 1}: '{worker_name}' returned an error."
                )

            history.append({"worker": worker_name, "task": task, "result": result})
            logger.info(f"[SupervisorAgent] hop {hop + 1}: {worker_name} done")

        # max_hops exhausted
        logger.info("[SupervisorAgent] Max hops reached — returning last successful result.")
        final_answer = self._last_successful_result(history, errored_workers_hbh)
        return await _finish(final_answer)

    # ------------------------------------------------------------------
    # LLM routing decision
    # ------------------------------------------------------------------

    async def _get_supervisor_decision(
        self,
        original_task: str,
        history: list[dict],
        worker_map: dict[str, str],
        *,
        force_finish: bool = False,
        called_workers: set | None = None,
        errored_workers: set | None = None,
    ) -> dict:
        """Ask the supervisor LLM what to do next and parse the JSON response."""
        worker_names = list(worker_map.keys())
        prompt = self._build_supervisor_prompt(
            original_task, history, worker_names, force_finish, called_workers, errored_workers
        )

        try:
            response = await asyncio.wait_for(
                self.supervisor_llm.ainvoke(prompt), timeout=60
            )
            response_text = (
                response.content if hasattr(response, "content") else str(response)
            )
        except asyncio.TimeoutError:
            logger.error("[SupervisorAgent] LLM call timed out after 60s")
            raise
        except Exception as e:
            logger.error(f"[SupervisorAgent] LLM call failed: {e}")
            # Smart fallback: if all workers have already produced output (or all have
            # been called), there is nothing left to do — return FINISH immediately
            # using the last successful worker's result as the answer.
            # Without this, the code defaults to the first worker, triggering
            # unnecessary extra hops and eventually producing a verbose history dump.
            called = called_workers or set()
            errored = errored_workers or set()
            succeeded = called - errored
            all_names = set(worker_names)
            if force_finish or (all_names and succeeded >= all_names) or (all_names and called >= all_names):
                # Find the last non-errored result in history to use as final answer
                final_answer = ""
                for h in reversed(history):
                    if h["worker"] not in errored:
                        final_answer = h["result"]
                        break
                if not final_answer:
                    final_answer = self._format_history(history) if history else original_task
                return {
                    "next": "FINISH",
                    "task": "",
                    "reasoning": f"LLM error (all workers done): {e}",
                    "final_answer": final_answer,
                }
            # Some workers still haven't run — pick the first uncalled worker
            uncalled = [n for n in worker_names if n not in called]
            default = uncalled[0] if uncalled else (worker_names[0] if worker_names else "FINISH")
            return {
                "next": default,
                "task": original_task,
                "reasoning": f"LLM error: {e}",
                "final_answer": "",
            }

        return self._parse_decision(response_text, worker_names)

    # ------------------------------------------------------------------
    # Plan-first execution
    # ------------------------------------------------------------------

    async def _plan_execution(
        self, original_task: str, worker_map: dict[str, str]
    ) -> list[dict[str, str]]:
        """Ask the LLM to plan the full execution as an ordered step list.

        Returns e.g.:
            [{"worker": "calculater_tool", "task": "Compute 1247 + 893"},
             {"worker": "summarize",       "task": "Summarize the calculation result"}]

        Each step's ``task`` contains ONLY that worker's specific subtask —
        not the combined user query.  Returns [] on failure so the caller
        can fall back to hop-by-hop routing.
        """
        worker_names = list(worker_map.keys())
        if not worker_names:
            return []

        worker_lines: list[str] = []
        for row in self.workers or []:
            if isinstance(row, dict):
                name = (row.get("worker_name") or "").strip()
                desc = (row.get("description") or "").strip()
                if name in worker_names:
                    worker_lines.append(f"- {name}: {desc}" if desc else f"- {name}")
        workers_block = "\n".join(worker_lines) or "No workers configured."

        prompt = f"""{self.system_prompt or ""}

**User Request:** {original_task}

**Available Workers:**
{workers_block}

Create an ordered execution plan for this request.

CRITICAL RULES:
- Each worker's "task" must contain ONLY that worker's specific job.
- Do NOT put two workers' responsibilities into one task.
- Include ONLY the workers genuinely needed.
- Order workers logically (e.g., calculate before summarize; research before analyze).

  "Do NOT add any summary, conclusion, or overview — that will be handled by the next worker."
  This prevents duplication and keeps each worker focused on its own job only.

Respond with ONLY a JSON array — no explanation, no markdown:
[
  {{"worker": "WorkerName", "task": "specific subtask for this worker only"}},
  ...
]

"worker" must be exactly one of: {json.dumps(worker_names)}"""

        try:
            response = await asyncio.wait_for(
                self.supervisor_llm.ainvoke(prompt), timeout=60
            )
            text = response.content if hasattr(response, "content") else str(response)

            clean = text.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()

            start = clean.find("[")
            end = clean.rfind("]") + 1
            if start == -1 or end <= start:
                logger.warning("[SupervisorAgent] _plan_execution: no JSON array found.")
                return []

            raw = json.loads(clean[start:end])
            plan: list[dict[str, str]] = []
            for step in raw:
                if isinstance(step, dict):
                    w = str(step.get("worker", "")).strip()
                    t = str(step.get("task", "")).strip()
                    if w in worker_names and t:
                        plan.append({"worker": w, "task": t})
            if plan:
                logger.info(
                    f"[SupervisorAgent] Plan created: {[s['worker'] for s in plan]}"
                )
            return plan
        except Exception as e:
            logger.warning(f"[SupervisorAgent] _plan_execution failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Worker invocation
    # ------------------------------------------------------------------

    async def _invoke_worker(self, vertex_id: str, task: str) -> str:
        """Directly build a worker vertex with the given task and return its result text.

        Works for any connected component — AgentNode, RunChildAgentComponent, or any
        custom node that accepts an ``input_value`` parameter.
        """
        vertex = self._vertex.graph.get_vertex(vertex_id)
        if vertex is None:
            return f"Worker vertex not found: {vertex_id}"

        # Pull the current LangGraph state stored by node_function just before build().
        lg_state: dict = getattr(self._vertex.graph, "_current_lg_state", {})

        # Resolve the worker's upstream dependencies (LLM, tools, child_agent_name, etc.)
        # from vertices_results — these were already built before the supervisor ran.
        state_results: dict = lg_state.get("vertices_results", {})
        resolved = _resolve_vertex_dependencies(vertex, {"vertices_results": state_results})
        if resolved:
            vertex.update_raw_params(resolved, overwrite=True)

        # Forward any uploaded files (images, documents) from the original user
        # message so workers can process them (e.g. vision models analysing images).
        files_from_state = lg_state.get("files") or []
        # Also check if the supervisor's own input_data carries files.
        if not files_from_state and isinstance(self.input_data, Message) and self.input_data.files:
            files_from_state = self.input_data.files

        # Override input_value with the task dispatched by the supervisor,
        # preserving any uploaded files so the worker LLM can see them.
        task_message = Message(text=task, files=files_from_state or [])
        vertex.update_raw_params({"input_value": task_message}, overwrite=True)

        # Reset built state so the vertex executes fresh on this hop.
        vertex.built = False
        vertex.built_object = None
        vertex.built_result = None

        # Propagate user_id so RunChildAgentComponent (and similar components) can
        # look up agents and execute child agents on behalf of the correct user.
        user_id = lg_state.get("user_id")

        # CRITICAL: vertex.build() internally calls _resolve_params() which scans
        # incoming graph edges.  The edge "Supervisor → Worker.input_value" points
        # back to *this* supervisor vertex.  Because supervisor.built == True,
        # _resolve_params() reads supervisor.built_result["Worker N"] = Message("")
        # (the empty stub returned by stop()) and OVERWRITES the task message we
        # just set above.
        #
        # Fix: temporarily mark the supervisor vertex as not-built so _resolve_params()
        # skips it.  The worker's other deps (agent_llm, tools) come from their own
        # vertices (which ARE built) and are resolved correctly by _resolve_vertex_dependencies()
        # + update_raw_params() above, so they survive the skip.
        supervisor_vertex = self._vertex
        supervisor_was_built = supervisor_vertex.built
        supervisor_vertex.built = False  # hide from worker's _resolve_params()
        try:
            # 120-second timeout per worker hop — prevents a hung LLM API call
            # (e.g. groq/moonshot returning no response) from freezing the entire
            # supervisor loop indefinitely.
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
            return self._extract_result(vertex.built_result)
        except asyncio.TimeoutError:
            logger.error(
                f"[SupervisorAgent] Worker vertex {vertex_id} timed out after 120 s"
            )
            return "Worker error: timed out — the worker's LLM did not respond in time."
        except Exception as e:
            logger.error(f"[SupervisorAgent] Worker vertex {vertex_id} raised: {e}")
            return f"Worker error: {e}"
        finally:
            # Restore supervisor built state — ChatOutput will read from supervisor's
            # built_result for the "Final Response" handle.
            supervisor_vertex.built = supervisor_was_built

    # ------------------------------------------------------------------
    # Dynamic output handles (driven by the workers table)
    # ------------------------------------------------------------------

    def update_outputs(self, frontend_node: dict, field_name: str, field_value: Any) -> dict:
        """Rebuild output handles whenever the workers table changes."""
        if field_name != "workers" or not field_value:
            return frontend_node

        outputs = []
        for row in field_value:
            if isinstance(row, dict):
                name = (row.get("worker_name") or "").strip()
                if name:
                    outputs.append(
                        Output(
                            display_name=name,
                            name=name,
                            method="supervisor_output",
                            group_outputs=True,
                            types=["Message"],
                        )
                    )

        # Always add Final Response as the last handle.
        outputs.append(
            Output(
                display_name="Final Response",
                name="Final Response",
                method="supervisor_output",
                group_outputs=True,
                types=["Message"],
            )
        )

        frontend_node["outputs"] = outputs
        return frontend_node

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_worker_map(self) -> dict[str, str]:
        """Return {worker_display_name: target_vertex_id} from graph edges.

        Tries three strategies in order so transient edge-format issues don't
        silently break routing:

        1. Primary  — read ``sourceHandle.name`` from ``graph.edges`` (raw dicts)
        2. Fallback — read the same field from ``raw_graph_data["edges"]``
        3. Heuristic — match workers table rows to non-output successors by position
        """
        graph = getattr(self._vertex, "graph", None)
        if graph is None:
            logger.error("[SupervisorAgent] _vertex.graph is None — cannot build worker map")
            return {}

        my_id = self._vertex.id

        # ── Strategy 1: graph.edges (processed, same as raw after process_agent) ─
        result = self._extract_worker_map_from_edges(
            getattr(graph, "edges", []), my_id, strategy="graph.edges"
        )
        if result:
            return result

        # ── Strategy 2: raw_graph_data["edges"] (original, pre-process_agent) ────
        raw_edges = graph.raw_graph_data.get("edges", []) if hasattr(graph, "raw_graph_data") else []
        if raw_edges:
            result = self._extract_worker_map_from_edges(raw_edges, my_id, strategy="raw_graph_data")
            if result:
                return result

        # ── Strategy 3: successor_map + workers table (positional heuristic) ─────
        result = self._build_worker_map_from_successors(graph, my_id)
        if result:
            logger.warning(
                "[SupervisorAgent] Using positional heuristic to build worker map "
                "(sourceHandle.name missing from edges — check edge serialisation)."
            )
            return result

        # ── Strategy 4: vertex scan (edges missing entirely) ──────────────────
        # Last resort when the Supervisor→Worker canvas connections are missing
        # from the graph (e.g. component refresh reset the static output handles
        # and the UI dropped the connections).  Finds AgentNode-type vertices by
        # scanning all graph vertices and matches them positionally to the workers
        # table sorted by canvas x-position.
        result = self._build_worker_map_from_vertex_scan(graph)
        if result:
            logger.warning(
                "[SupervisorAgent] Using vertex-scan fallback to build worker map "
                "(no Supervisor→Worker edges found). "
                "Please reconnect worker agents in the canvas for reliable routing."
            )
            return result

        # All strategies failed — log diagnostic info so the next run is debuggable.
        all_edges = getattr(graph, "edges", [])
        my_edges = [e for e in all_edges if e.get("source") == my_id]
        raw_my_edges = [
            e for e in (graph.raw_graph_data.get("edges", []) if hasattr(graph, "raw_graph_data") else [])
            if e.get("source") == my_id
        ]
        vertex_ids = [v.id for v in getattr(graph, "vertices", [])]
        logger.error(
            f"[SupervisorAgent] _get_worker_map() returned empty.\n"
            f"  supervisor vertex id      : {my_id!r}\n"
            f"  total edges in graph      : {len(all_edges)}\n"
            f"  edges from supervisor     : {len(my_edges)}\n"
            f"  raw edges from supervisor : {len(raw_my_edges)}\n"
            f"  first 3 sup-edges         : {my_edges[:3]}\n"
            f"  first 3 raw sup-edges     : {raw_my_edges[:3]}\n"
            f"  all vertex ids            : {vertex_ids}\n"
            f"  workers table             : {self.workers}\n"
            f"  successor_map entry       : {getattr(graph, 'successor_map', {}).get(my_id, [])}"
        )
        return {}

    @staticmethod
    def _extract_worker_map_from_edges(
        edges: list, my_id: str, *, strategy: str
    ) -> dict[str, str]:
        """Extract {worker_name: target_id} by reading sourceHandle.name from a list of edge dicts."""
        result: dict[str, str] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            if edge.get("source") != my_id:
                continue
            target = edge.get("target", "")
            if not target:
                continue
            sh = edge.get("data", {}).get("sourceHandle", {})
            # sourceHandle can be a dict or (rarely) a JSON string
            if isinstance(sh, str):
                try:
                    import json as _json
                    sh = _json.loads(sh)
                except Exception:
                    sh = {}
            name = (sh.get("name") or "") if isinstance(sh, dict) else ""
            if name and name != "Final Response":
                result[name] = target
        if result:
            logger.debug(f"[SupervisorAgent] worker map built via {strategy}: {list(result.keys())}")
        return result

    def _build_worker_map_from_successors(self, graph: Any, my_id: str) -> dict[str, str]:
        """Heuristic fallback: map workers table rows to successor vertices by position.

        Uses ``graph.edges`` (an ordered list) to preserve the order in which the
        user connected handles, then skips ChatOutput-type (interface) vertices.
        Positional matching is imperfect but far better than returning ``{}``.
        """
        # Collect non-output successor IDs in edge-list order (preserves user's draw order)
        ordered_worker_targets: list[str] = []
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
            ordered_worker_targets.append(target)
            seen.add(target)

        worker_names: list[str] = [
            (r.get("worker_name") or "").strip()
            for r in (self.workers or [])
            if isinstance(r, dict) and (r.get("worker_name") or "").strip()
        ]
        result: dict[str, str] = {}
        for i, name in enumerate(worker_names):
            if i >= len(ordered_worker_targets):
                break
            result[name] = ordered_worker_targets[i]
        return result

    def _build_worker_map_from_vertex_scan(self, graph: Any) -> dict[str, str]:
        """Strategy 4: find worker vertices by scanning all graph vertices.

        Used when Supervisor→Worker edges are completely absent (e.g. the canvas
        connections were dropped after a component refresh changed the static
        output handles).  Candidates are vertices that:
          * are not the supervisor itself
          * are not interface components (ChatInput/ChatOutput)
          * are not pure input/output nodes
          * have ``input_value`` in their template (task-accepting agents)
          OR whose base_name is "AgentNode" / "RunChildAgentComponent"

        Candidates are sorted by canvas x-position so that the left-to-right
        ordering on the canvas matches the top-to-bottom order in the workers table.
        """
        worker_names: list[str] = [
            (r.get("worker_name") or "").strip()
            for r in (self.workers or [])
            if isinstance(r, dict) and (r.get("worker_name") or "").strip()
        ]
        if not worker_names:
            return {}

        my_id = self._vertex.id
        _supervisor_types = {"SupervisorAgent", "CollaborativeAgent"}
        _agent_base_names = {"AgentNode", "RunChildAgentComponent"}

        candidates = []
        for vertex in getattr(graph, "vertices", []):
            if vertex.id == my_id:
                continue
            if getattr(vertex, "is_interface_component", False):
                continue
            if getattr(vertex, "is_input", False) or getattr(vertex, "is_output", False):
                continue
            if vertex.base_name in _supervisor_types or getattr(vertex, "vertex_type", "") in _supervisor_types:
                continue
            # Accept vertices that look like task-accepting agents
            has_input_value = "input_value" in getattr(vertex, "template", {})
            is_agent_type = vertex.base_name in _agent_base_names
            if not (has_input_value or is_agent_type):
                continue
            candidates.append(vertex)

        if not candidates:
            return {}

        # Sort by canvas x-position (preserves left-to-right worker order)
        def _sort_key(v: Any) -> tuple:
            pos = v.full_data.get("position", {}) if hasattr(v, "full_data") else {}
            return (pos.get("x", 0), pos.get("y", 0), v.id)

        candidates.sort(key=_sort_key)

        result: dict[str, str] = {}
        for i, name in enumerate(worker_names):
            if i >= len(candidates):
                break
            result[name] = candidates[i].id
        return result

    def _build_supervisor_prompt(
        self,
        original_task: str,
        history: list[dict],
        worker_names: list[str],
        force_finish: bool = False,
        called_workers: set | None = None,
        errored_workers: set | None = None,
    ) -> str:
        called = called_workers or set()
        errored = errored_workers or set()
        succeeded = called - errored  # workers that ran successfully

        # Worker descriptions block — tag each worker's status
        worker_lines: list[str] = []
        for row in self.workers or []:
            if isinstance(row, dict):
                name = (row.get("worker_name") or "").strip()
                desc = (row.get("description") or "").strip()
                if name:
                    if name in errored:
                        tag = " ❌ [returned error — blocked]"
                    elif name in succeeded:
                        tag = " ✅ [already produced output — do NOT call again]"
                    else:
                        tag = ""
                    line = f"- **{name}**{tag}: {desc}" if desc else f"- **{name}**{tag}"
                    worker_lines.append(line)
        workers_block = "\n".join(worker_lines) or "No workers configured."

        # History block — annotate each step with its status
        if history:
            steps = []
            for i, h in enumerate(history, 1):
                if h["worker"] in errored:
                    status_note = " ❌ ERROR — do NOT call this worker again."
                elif h["worker"] in succeeded:
                    status_note = " ✅ Done."
                else:
                    status_note = ""
                steps.append(
                    f"[Step {i}] Called **{h['worker']}**: \"{h['task']}\"\n"
                    f"Response: {h['result']}{status_note}"
                )
            history_block = "\n\n".join(steps)
        else:
            history_block = "None yet."

        # Summary of blocked/completed workers
        notes: list[str] = []
        if errored:
            blocked = ", ".join(f"**{w}**" for w in sorted(errored))
            notes.append(f"⚠️ Workers with errors (do NOT call again): {blocked}")
        if succeeded:
            done = ", ".join(f"**{w}**" for w in sorted(succeeded))
            notes.append(
                f"✅ Workers that already produced output (do NOT repeat): {done}. "
                "Call a different worker or set next to FINISH."
            )
        extra_block = ("\n\n" + "\n".join(notes)) if notes else ""

        valid_names_str = json.dumps(worker_names + ["FINISH"])
        finish_note = (
            ' You MUST set "next" to "FINISH" and provide a complete "final_answer".'
            if force_finish
            else ""
        )

        return f"""{self.system_prompt or ""}

**Original Task:** {original_task}

**Available Workers (only call those relevant to the task):**
{workers_block}{extra_block}

**Work completed so far:**
{history_block}

**Decide the next step.**{finish_note}
Rules:
- Call a worker only if it has not been called yet AND the task genuinely requires it.
- If a worker already produced output (✅), do NOT call it again — set next to FINISH instead.
- If a worker returned an error (❌), do NOT call it again.
Respond ONLY with a JSON object.

If another (uncalled) worker is still needed:
{{"next": "WorkerName", "task": "Specific instructions for this worker", "reasoning": "Why this worker is needed"}}

If the task is complete (all necessary work done):
{{"next": "FINISH", "task": "", "reasoning": "Why done"}}

IMPORTANT: When you set next to FINISH, the framework will automatically return the last
worker's response to the user. Do NOT add a "final_answer" field — the last worker's output
is used as-is without any re-synthesis.

"next" must be exactly one of: {valid_names_str}"""

    def _parse_decision(self, text: str, valid_names: list[str]) -> dict:
        """Parse an LLM response into a routing decision dict."""
        try:
            clean = text.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()

            start = clean.find("{")
            end = clean.rfind("}") + 1
            if start != -1 and end > start:
                parsed = json.loads(clean[start:end])
                next_val = str(parsed.get("next", "")).strip()
                if next_val == "FINISH" or next_val in valid_names:
                    return {
                        "next": next_val,
                        "task": parsed.get("task", ""),
                        "reasoning": parsed.get("reasoning", ""),
                        "final_answer": parsed.get("final_answer", ""),
                    }
        except (json.JSONDecodeError, IndexError, KeyError):
            pass

        # Fallback: scan the raw text for known names
        text_lower = text.lower()
        if "finish" in text_lower:
            return {
                "next": "FINISH",
                "task": "",
                "reasoning": "Parsed FINISH from response text",
                "final_answer": text[:500],
            }
        for name in valid_names:
            if name.lower() in text_lower:
                return {
                    "next": name,
                    "task": text[:300],
                    "reasoning": "Extracted worker name from response text",
                    "final_answer": "",
                }

        default = valid_names[0] if valid_names else "FINISH"
        logger.warning(
            f"[SupervisorAgent] Could not parse LLM decision from: {text[:200]!r}. "
            f"Defaulting to '{default}'."
        )
        return {
            "next": default,
            "task": "",
            "reasoning": "JSON parse failed — using default worker",
            "final_answer": "",
        }

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

    @staticmethod
    def _extract_result(built_result: Any) -> str:
        """Extract a plain string from a vertex's built_result.

        ``built_result`` is typically a dict keyed by output-handle name
        (e.g. ``{"response": Message(...)}``) for multi-output components,
        or a bare ``Message`` / ``Data`` for single-output ones.
        """
        if built_result is None:
            return ""
        if isinstance(built_result, Message):
            return built_result.text or ""
        if isinstance(built_result, Data):
            return str(built_result.data)
        if isinstance(built_result, dict):
            # Prefer the first Message value with content.
            for v in built_result.values():
                if isinstance(v, Message) and v.text:
                    return v.text
            # Fall back to first Data value.
            for v in built_result.values():
                if isinstance(v, Data):
                    return str(v.data)
            # Last resort: first non-empty value.
            for v in built_result.values():
                if v:
                    return str(v)
        return str(built_result)

    @staticmethod
    def _last_successful_result(history: list[dict], errored_workers: set) -> str:
        """Return the last non-errored worker's result, or a formatted history dump."""
        for h in reversed(history):
            if h["worker"] not in errored_workers and h["result"]:
                return h["result"]
        # All workers errored — fall back to full history so nothing is lost
        return "\n\n".join(
            f"[{h['worker']}] {h['result']}" for h in history
        ) if history else ""

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        """Format accumulated history as a readable string."""
        if not history:
            return "No work completed."
        return "\n\n".join(
            f"[{h['worker']}]\nTask: {h['task']}\nResult: {h['result']}"
            for h in history
        )
