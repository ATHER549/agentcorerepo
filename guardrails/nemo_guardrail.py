import asyncio
import concurrent.futures
from typing import Any
from uuid import UUID

from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.inputs.inputs import BoolInput, MessageTextInput, MultilineInput
from agentcore.io import DropdownInput, Output
from agentcore.schema.message import Message
from agentcore.components.models._rbac_helpers import resolve_user_id
from agentcore.services.guardrail_service_client import (
    apply_nemo_guardrail_via_service,
    list_active_guardrails_via_service,
)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        return asyncio.run(coro)


def _fetch_active_guardrail_options(user_id: str | None = None) -> list[str]:
    async def _query() -> list[str]:
        try:
            items = await list_active_guardrails_via_service(user_id=user_id)
        except Exception:  # noqa: BLE001
            logger.exception("NeMo guardrail dropdown options query failed (service unavailable).")
            return []

        options: list[str] = []
        runtime_ready_count = 0
        for item in items:
            name = item.get("name", "")
            gid = item.get("id", "")
            is_ready = bool(item.get("runtime_ready", False))
            label = name if is_ready else f"{name} (Runtime incomplete)"
            if is_ready:
                runtime_ready_count += 1
            options.append(f"{label} | {gid}")

        logger.info(
            "NeMo guardrail dropdown options loaded via service: "
            f"total={len(items)}, runtime_ready={runtime_ready_count}, "
            f"runtime_incomplete={len(items) - runtime_ready_count}"
        )
        return options

    try:
        return _run_async(_query())
    except Exception:  # noqa: BLE001
        logger.exception("NeMo guardrail dropdown options query failed.")
        return []


class NemoGuardrailComponent(Node):
    display_name = "NeMo Guardrails"
    description = "Apply NeMo Guardrails to validate and filter text using a configured guardrail profile."
    icon = "Shield"
    name = "NemoGuardrails"
    trace_type = "guardrail"

    inputs = [
        MessageTextInput(
            name="input_text",
            display_name="Input Text",
            info="The text to validate through guardrails.",
            tool_mode=True,
            required=True,
        ),
        DropdownInput(
            name="guardrail_id",
            display_name="Guardrail ID",
            info="Guardrail UUID from the Guardrails Catalogue runtime configuration.",
            options=[],
            value="",
            refresh_button=True,
            real_time_refresh=True,
            combobox=True,
            required=False,
        ),
        BoolInput(
            name="enabled",
            display_name="Enabled",
            info="If disabled, this component passes the input through unchanged.",
            value=True,
        ),
        BoolInput(
            name="fail_open",
            display_name="Fail Open",
            info="If guardrail execution fails, pass input through unchanged instead of blocking.",
            value=True,
            advanced=False,
        ),
        MultilineInput(
            name="blocked_message",
            display_name="Blocked Message",
            info="Returned when guardrails block content or fail in fail-closed mode.",
            value="Your request was blocked by configured safety guardrails.",
            advanced=False,
        ),
    ]

    outputs = [
        Output(display_name="Safe", name="output", type_=Message, method="safe_output", group_outputs=True),
        Output(display_name="Blocked", name="blocked_output", type_=Message, method="blocked_output", group_outputs=True),
    ]

    def _pre_run_setup(self):
        self._decision_evaluated = False
        self.trace_output_metadata = {}
        self._decision: dict[str, Any] = {
            "blocked": False,
            "safe_text": "",
            "blocked_text": self.blocked_message,
            "action": "passthrough",
            "guardrail_id": "",
            "status": "",
        }

    @staticmethod
    def _extract_guardrail_uuid(raw_value: str | None) -> str:
        if not isinstance(raw_value, str):
            return ""
        value = raw_value.strip()
        if "|" in value:
            value = value.split("|")[-1].strip()
        return value

    def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None):  # noqa: ARG002
        if field_name in {"guardrail_id", None}:
            current_user_id = resolve_user_id(self)
            options = _fetch_active_guardrail_options(user_id=current_user_id)
            build_config["guardrail_id"]["options"] = options
            current_value = build_config["guardrail_id"].get("value", "")
            if options and current_value not in options:
                build_config["guardrail_id"]["value"] = options[0]
            logger.info(
                "NeMo guardrail node config refreshed: "
                f"options_count={len(options)}, selected_value={build_config['guardrail_id'].get('value', '')}"
            )
        return build_config

    def _is_output_connected(self, output_name: str) -> bool:
        if not self._vertex:
            return False
        return output_name in self._vertex.edges_source_names

    async def _evaluate_guardrail_decision(self) -> dict[str, Any]:
        if getattr(self, "_decision_evaluated", False):
            return self._decision

        input_text = self.input_text if isinstance(self.input_text, str) else str(self.input_text or "")
        guardrail_id = self._extract_guardrail_uuid(self.guardrail_id)
        logger.info(
            "NeMo guardrail node execution started: "
            f"guardrail_id={guardrail_id or 'none'}, enabled={bool(self.enabled)}, fail_open={bool(self.fail_open)}, "
            f"input_length={len(input_text)}"
        )
        decision: dict[str, Any] = {
            "blocked": False,
            "safe_text": input_text,
            "blocked_text": self.blocked_message,
            "action": "passthrough",
            "guardrail_id": guardrail_id,
            "status": "",
        }

        if not self.enabled:
            decision["status"] = "Guardrails disabled; input passed through."
            logger.info("NeMo guardrail node bypassed because it is disabled.")
            self._decision = decision
            self._decision_evaluated = True
            return decision

        if not guardrail_id:
            decision["status"] = "No guardrail ID provided; input passed through."
            logger.warning("NeMo guardrail node bypassed because guardrail_id is missing.")
            self._decision = decision
            self._decision_evaluated = True
            return decision

        # Detect production context — prod agents must use the frozen prod guardrail copy
        environment: str | None = None
        if self._vertex:
            is_prod = bool(getattr(self._vertex.graph, "prod_deployment_id", None))
            if is_prod:
                environment = "prod"
                logger.info(
                    "NeMo guardrail node detected production context: "
                    f"guardrail_id={guardrail_id}, prod_deployment_id={getattr(self._vertex.graph, 'prod_deployment_id', None)}"
                )

        try:
            result = await apply_nemo_guardrail_via_service(
                input_text=input_text,
                guardrail_id=guardrail_id,
                environment=environment,
            )
            self.trace_output_metadata = {
                "agentcore_usage": {
                    "source": "nemoguardrails",
                    "component": self.name,
                    "guardrail_id": result.get("guardrail_id"),
                    "llm_calls_count": int(result.get("llm_calls_count") or 0),
                    "input_tokens": int(result.get("input_tokens") or 0),
                    "output_tokens": int(result.get("output_tokens") or 0),
                    "total_tokens": int(result.get("total_tokens") or 0),
                    "model": result.get("model"),
                    "provider": result.get("provider"),
                }
            }
            logger.info(
                "NeMo guardrail node usage metadata prepared: "
                f"guardrail_id={result.get('guardrail_id')}, llm_calls={result.get('llm_calls_count')}, "
                f"input_tokens={result.get('input_tokens')}, output_tokens={result.get('output_tokens')}, "
                f"total_tokens={result.get('total_tokens')}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"NeMo guardrail node execution failed: guardrail_id={guardrail_id}")
            if self.fail_open:
                decision["status"] = f"Guardrail execution failed in fail-open mode: {exc}"
                logger.warning(
                    "NeMo guardrail node fail-open fallback used: "
                    f"guardrail_id={guardrail_id}, exception={exc}"
                )
                self._decision = decision
                self._decision_evaluated = True
                asyncio.ensure_future(self._log_guardrail_execution(decision))
                return decision

            decision["blocked"] = True
            decision["action"] = "blocked"
            decision["status"] = f"Guardrail execution failed in fail-closed mode: {exc}"
            logger.warning(
                "NeMo guardrail node fail-closed block returned: "
                f"guardrail_id={guardrail_id}, exception={exc}"
            )
            self._decision = decision
            self._decision_evaluated = True
            asyncio.ensure_future(self._log_guardrail_execution(decision))
            return decision

        action = result.get("action", "passthrough")
        if action == "blocked":
            decision["blocked"] = True
            decision["action"] = action
            decision["guardrail_id"] = result.get("guardrail_id", guardrail_id)
            decision["status"] = f"Guardrail action=blocked (guardrail_id={result.get('guardrail_id')})"
            logger.warning(f"NeMo guardrail node blocked content: guardrail_id={result.get('guardrail_id')}")
            self._decision = decision
            self._decision_evaluated = True
            asyncio.ensure_future(self._log_guardrail_execution(decision))
            return decision

        decision["blocked"] = False
        decision["action"] = action
        decision["guardrail_id"] = result.get("guardrail_id", guardrail_id)
        decision["status"] = f"Guardrail action={action} (guardrail_id={result.get('guardrail_id')})"

        # For masked/rewritten content, use the guardrail's modified output.
        # For passthrough, keep the original input to avoid prompt drift.
        if action in ("masked", "rewritten"):
            decision["safe_text"] = result.get("output_text", input_text)
            logger.info(
                f"NeMo guardrail returned {action} text, forwarding modified output: "
                f"guardrail_id={result.get('guardrail_id')}, output_length={len(result.get('output_text', ''))}"
            )
        else:
            decision["safe_text"] = input_text
        logger.info(
            "NeMo guardrail node execution completed: "
            f"guardrail_id={result.get('guardrail_id')}, action={action}, "
            f"output_length={len(result.get('output_text', ''))}"
        )
        self._decision = decision
        self._decision_evaluated = True
        asyncio.ensure_future(self._log_guardrail_execution(decision))
        return decision

    async def _log_guardrail_execution(self, decision: dict[str, Any]) -> None:
        """Persist guardrail execution result to DB for dashboard KPIs. Fire-and-forget."""
        try:
            from sqlmodel import select

            from agentcore.services.database.models.agent.model import Agent
            from agentcore.services.database.models.guardrail_execution_log.model import GuardrailExecutionLog
            from agentcore.services.deps import session_scope

            agent_id: UUID | None = None
            if self._vertex and hasattr(self._vertex, "graph"):
                raw = getattr(self._vertex.graph, "agent_id", None)
                if raw:
                    agent_id = UUID(str(raw)) if not isinstance(raw, UUID) else raw

            action = decision.get("action", "passthrough")
            environment = None
            if self._vertex and bool(getattr(self._vertex.graph, "prod_deployment_id", None)):
                environment = "prod"

            async with session_scope() as session:
                org_id: UUID | None = None
                if agent_id:
                    result = (await session.exec(select(Agent.org_id).where(Agent.id == agent_id))).first()
                    if result is not None:
                        org_id = result

                user_id: UUID | None = None
                raw_user = getattr(self, "_user_id", None)
                if raw_user:
                    user_id = UUID(str(raw_user)) if not isinstance(raw_user, UUID) else raw_user

                log_entry = GuardrailExecutionLog(
                    guardrail_id=decision.get("guardrail_id", ""),
                    agent_id=agent_id,
                    org_id=org_id,
                    user_id=user_id,
                    session_id=getattr(self, "session_id", None),
                    action=action,
                    is_violation=(action != "passthrough"),
                    environment=environment,
                )
                session.add(log_entry)
        except Exception:
            logger.warning("Failed to log guardrail execution to DB", exc_info=True)

    async def safe_output(self) -> Message:
        """Route safe content forward (typically to LLM)."""
        decision = await self._evaluate_guardrail_decision()

        if decision["blocked"]:
            self.status = decision["status"]
            if self._is_output_connected("blocked_output"):
                # Stop safe branch so downstream LLM is not executed.
                self.stop("output")
                return Message(text="")

            # Backward-compatible fallback for legacy single-output graphs.
            # In this case we can't short-circuit and return a message unless there is a blocked branch.
            logger.warning(
                "NeMo guardrail blocked content but blocked_output is not connected; "
                "falling back to legacy behavior by returning blocked message on safe output."
            )
            return Message(text=decision["blocked_text"])

        # Disable blocked branch for safe traffic.
        self.stop("blocked_output")
        self.status = decision["status"]
        return Message(text=decision["safe_text"])

    async def apply_guardrails(self) -> Message:
        """Backward-compatible alias for older graphs that still reference this method name."""
        return await self.safe_output()

    async def blocked_output(self) -> Message:
        """Route blocked content to response path and short-circuit LLM path."""
        decision = await self._evaluate_guardrail_decision()

        if decision["blocked"]:
            # Ensure LLM branch is not executed for blocked content.
            self.stop("output")
            self.status = decision["status"]
            return Message(text=decision["blocked_text"])

        # Disable blocked branch when content is safe.
        self.stop("blocked_output")
        self.status = decision["status"]
        return Message(text="")
