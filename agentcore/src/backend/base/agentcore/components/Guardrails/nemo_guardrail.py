import asyncio
import concurrent.futures
from typing import Any

from loguru import logger
from sqlmodel import select

from agentcore.custom.custom_node.node import Node
from agentcore.inputs.inputs import BoolInput, MessageTextInput, MultilineInput
from agentcore.io import DropdownInput, Output
from agentcore.schema.message import Message
from agentcore.services.database.models.guardrail_catalogue.model import GuardrailCatalogue
from agentcore.services.database.models.model_registry.model import ModelRegistry
from agentcore.services.deps import session_scope
from agentcore.services.guardrails import apply_nemo_guardrail_text, is_nemo_runtime_config_ready


def _run_async(coro):
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        return asyncio.run(coro)


def _fetch_active_guardrail_options() -> list[str]:
    async def _query() -> list[str]:
        async with session_scope() as session:
            stmt = (
                select(GuardrailCatalogue)
                .where(
                    GuardrailCatalogue.framework == "nemo",
                    GuardrailCatalogue.status == "active",
                    GuardrailCatalogue.model_registry_id.is_not(None),
                )
                .order_by(GuardrailCatalogue.name.asc())
            )
            rows = (await session.exec(stmt)).all()
            total_rows = len(rows)
            model_ids = {row.model_registry_id for row in rows if row.model_registry_id}
            if not model_ids:
                logger.warning(
                    "NeMo guardrail dropdown query returned no model-linked active guardrails: "
                    f"active_guardrails={total_rows}"
                )
                return []
            active_model_ids = set(
                await session.exec(
                    select(ModelRegistry.id).where(
                        ModelRegistry.id.in_(list(model_ids)),
                        ModelRegistry.is_active.is_(True),
                    )
                )
            )
            selectable_rows = [row for row in rows if row.model_registry_id in active_model_ids]
            options: list[str] = []
            runtime_ready_count = 0
            for row in selectable_rows:
                is_ready = is_nemo_runtime_config_ready(row.runtime_config, row.model_registry_id)
                label = row.name if is_ready else f"{row.name} (Runtime incomplete)"
                if is_ready:
                    runtime_ready_count += 1
                options.append(f"{label} | {row.id}")
            logger.info(
                "NeMo guardrail dropdown options loaded: "
                f"active_guardrails={total_rows}, active_model_guardrails={len(selectable_rows)}, "
                f"runtime_ready={runtime_ready_count}, runtime_incomplete={len(selectable_rows) - runtime_ready_count}"
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

    def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None):
        if field_name in {"guardrail_id", None}:
            options = _fetch_active_guardrail_options()
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

        try:
            result = await apply_nemo_guardrail_text(
                input_text=input_text,
                guardrail_id=guardrail_id,
            )
            self.trace_output_metadata = {
                "agentcore_usage": {
                    "source": "nemoguardrails",
                    "component": self.name,
                    "guardrail_id": result.guardrail_id,
                    "llm_calls_count": int(result.llm_calls_count or 0),
                    "input_tokens": int(result.input_tokens or 0),
                    "output_tokens": int(result.output_tokens or 0),
                    "total_tokens": int(result.total_tokens or 0),
                    "model": result.model,
                    "provider": result.provider,
                }
            }
            logger.info(
                "NeMo guardrail node usage metadata prepared: "
                f"guardrail_id={result.guardrail_id}, llm_calls={result.llm_calls_count}, "
                f"input_tokens={result.input_tokens}, output_tokens={result.output_tokens}, total_tokens={result.total_tokens}"
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
            return decision

        if result.action == "blocked":
            decision["blocked"] = True
            decision["action"] = result.action
            decision["guardrail_id"] = result.guardrail_id
            decision["status"] = f"Guardrail action=blocked (guardrail_id={result.guardrail_id})"
            logger.warning(f"NeMo guardrail node blocked content: guardrail_id={result.guardrail_id}")
            self._decision = decision
            self._decision_evaluated = True
            return decision

        decision["blocked"] = False
        # For input-guardrail topology, keep safe traffic unchanged to avoid prompt drift.
        decision["safe_text"] = input_text
        decision["action"] = result.action
        decision["guardrail_id"] = result.guardrail_id
        decision["status"] = f"Guardrail action={result.action} (guardrail_id={result.guardrail_id})"
        if result.action == "rewritten":
            logger.warning(
                "NeMo guardrail returned rewritten text but node is forwarding original input as configured: "
                f"guardrail_id={result.guardrail_id}, rewritten_output_length={len(result.output_text)}"
            )
        logger.info(
            "NeMo guardrail node execution completed: "
            f"guardrail_id={result.guardrail_id}, action={result.action}, output_length={len(result.output_text)}"
        )
        self._decision = decision
        self._decision_evaluated = True
        return decision

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
