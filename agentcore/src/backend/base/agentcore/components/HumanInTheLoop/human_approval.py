"""Human Approval component — pauses graph execution for human review.

Uses LangGraph's interrupt() to genuinely pause the graph and wait for
a human decision. Requires the compiled graph to have a checkpointer.

Trigger modes:
  1. Always Pause  — every execution pauses for human review.
  2. Business Rules — configurable conditions (field, operator, value).
                     Only pauses when rules match; auto-approves otherwise.
  3. AI-Decided    — an LLM evaluates the input against natural language
                     business rules to decide if approval is needed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langgraph.types import interrupt
from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.io import (
    DropdownInput,
    HandleInput,
    MultilineInput,
    Output,
    SliderInput,
    TableInput,
)
from agentcore.schema.data import Data
from agentcore.schema.dotdict import dotdict
from agentcore.schema.message import Message


class HumanApprovalComponent(Node):
    """Pause graph execution and wait for a human decision.

    The graph is genuinely paused via LangGraph interrupt().
    The frontend polls GET /hitl/{thread_id}/state to show the approval card,
    and POSTs to /hitl/{thread_id}/resume with the chosen action.
    """

    display_name = "Human Approval"
    description = (
        "Pause workflow execution and wait for a human to review and take action. "
        "Supports configurable action buttons (Approve / Reject / Edit / etc.)."
    )
    icon = "UserCheck"
    name = "HumanApproval"
    beta = False

    inputs = [
        HandleInput(
            name="input_value",
            display_name="Input",
            info="Content to present to the human reviewer.",
            input_types=["Message", "Data", "str"],
            required=True,
        ),
        DropdownInput(
            name="trigger_mode",
            display_name="Trigger Mode",
            info="When to require human approval.",
            options=["Always Pause", "Business Rules", "AI-Decided"],
            value="Always Pause",
            real_time_refresh=True,
        ),
        MultilineInput(
            name="approval_message",
            display_name="Review Question",
            info="Question or instructions shown to the human reviewer.",
            value="Please review the content above and choose an action:",
        ),
        TableInput(
            name="business_rules",
            display_name="Business Rules",
            info=(
                "Conditions that trigger human approval. "
                "Use dot notation for nested fields (e.g. 'data.amount')."
            ),
            table_schema=[
                {
                    "name": "field_path",
                    "display_name": "Field",
                    "type": "str",
                    "description": "Field name or dot-path to extract from input",
                    "edit_mode": "inline",
                },
                {
                    "name": "operator",
                    "display_name": "Operator",
                    "type": "str",
                    "description": "Comparison operator for the rule",
                    "options": ["equals", "not equals", "contains", ">", ">=", "<", "<=", "regex"],
                    "default": "equals",
                    "edit_mode": "inline",
                },
                {
                    "name": "value",
                    "display_name": "Value",
                    "type": "str",
                    "description": "Value to compare against",
                    "edit_mode": "inline",
                },
            ],
            value=[],
            show=False,
            advanced=True,
        ),
        DropdownInput(
            name="match_logic",
            display_name="Match Logic",
            info="'Any' = pause if ANY rule matches. 'All' = pause only if ALL rules match.",
            options=["Any", "All"],
            value="Any",
            show=False,
            advanced=True,
        ),
        HandleInput(
            name="evaluation_llm",
            display_name="Language Model",
            info="LLM used to evaluate whether the input needs human approval.",
            input_types=["LanguageModel"],
            required=False,
            show=False,
            advanced=True,
        ),
        MultilineInput(
            name="rule_description",
            display_name="Rule Description",
            info="Describe in natural language when human approval is needed. The LLM evaluates the input against these rules.",
            value="",
            show=False,
            advanced=True,
        ),
        TableInput(
            name="actions",
            display_name="Actions",
            info="Define the action buttons the reviewer will see.",
            table_schema=[
                {
                    "name": "action_name",
                    "display_name": "Action Name",
                    "type": "str",
                    "description": "Label shown on the button (e.g. Approve, Reject, Edit)",
                },
            ],
            value=[
                {"action_name": "Approve"},
                {"action_name": "Reject"},
            ],
            real_time_refresh=True,
        ),
        SliderInput(
            name="timeout_seconds",
            display_name="Timeout (seconds)",
            info="Seconds to wait before auto-routing to the first action. 0 = no timeout.",
            value=0,
            range_spec={"min": 0, "max": 3600, "step": 30},
            advanced=True,
        ),
    ]

    # Default outputs — replaced dynamically by update_outputs()
    outputs = [
        Output(
            display_name="Approve",
            name="Approve",
            method="action_output",
            group_outputs=True,
            types=["Message", "Data"],
        ),
        Output(
            display_name="Reject",
            name="Reject",
            method="action_output",
            group_outputs=True,
            types=["Message", "Data"],
        ),
    ]

    # ── Input parsing helpers ────────────────────────────────────────────────

    def _extract_content(self) -> str:
        """Extract string content from whatever was passed as input."""
        val = self.input_value
        if val is None:
            return ""
        if isinstance(val, Message):
            return val.text or ""
        if isinstance(val, Data):
            if isinstance(val.data, dict):
                return json.dumps(val.data, indent=2)
            return str(val.data)
        return str(val)

    @staticmethod
    def _extract_kv_from_text(text: str) -> dict:
        """Extract key-value pairs from natural language text.

        Patterns matched: "key is value", "key: value", "key = value"
        Delimiters: comma, semicolon, newline, " and ".
        Always includes a "text" key with the original string.
        """
        result: dict[str, str] = {"text": text}
        segments = re.split(r'[,;\n]|\band\b', text)
        kv_pattern = re.compile(
            r'^\s*(\w[\w\s]*?)\s*(?:is|:|=)\s*(.+?)\s*$',
            re.IGNORECASE,
        )
        for segment in segments:
            m = kv_pattern.match(segment.strip())
            if m:
                key = m.group(1).strip().lower().replace(" ", "_")
                value = m.group(2).strip()
                result[key] = value
        return result

    def _parse_input_as_dict(self) -> dict:
        """Convert input_value (Message/Data/str) to a dict for rule evaluation.

        Handles:
        1. Data.data dict → merge KV pairs extracted from "text" field
        2. JSON string → parse
        3. Plain text / Message → extract key-value pairs from NL
        """
        val = self.input_value
        if val is None:
            return {}

        # Data object wrapping a dict (e.g. full message record)
        if isinstance(val, Data) and isinstance(val.data, dict):
            data = dict(val.data)  # shallow copy so we don't mutate original
            # Always extract KV pairs from the "text" field and merge them in.
            # The Data dict is typically a message record with keys like
            # timestamp, sender, session_id, text, etc. Business rules
            # reference fields like "amount" that only exist inside the text.
            text_val = data.get("text", "")
            if isinstance(text_val, str) and text_val.strip():
                # Try JSON first (user may send '{"amount": "6000"}')
                try:
                    parsed = json.loads(text_val.strip())
                    if isinstance(parsed, dict):
                        for k, v in parsed.items():
                            if k not in data:
                                data[k] = v
                        logger.info(
                            f"[HumanApproval] Parsed input (Data+JSON): "
                            f"extracted keys={list(parsed.keys())}"
                        )
                        return data
                except (json.JSONDecodeError, TypeError):
                    pass
                # Fall back to NL key-value extraction ("amount is 6000")
                kv = self._extract_kv_from_text(text_val)
                for k, v in kv.items():
                    if k not in data:  # don't overwrite existing real keys
                        data[k] = v
                logger.info(
                    f"[HumanApproval] Parsed input (Data+KV): "
                    f"extracted keys={[k for k in kv if k != 'text']}"
                )
            else:
                logger.info("[HumanApproval] Parsed input (Data dict, no text to parse)")
            return data

        # Get raw text
        text = ""
        if isinstance(val, Message):
            text = val.text or ""
        elif isinstance(val, str):
            text = val
        else:
            text = str(val)

        # Try JSON first
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                logger.info(f"[HumanApproval] Parsed input (JSON): {parsed}")
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        # Extract key-value pairs from natural language
        result = self._extract_kv_from_text(text)
        logger.info(f"[HumanApproval] Parsed input (NL→KV): {result}")
        return result

    def _extract_field(self, data: dict, field_path: str) -> Any:
        """Extract a value from a dict using dot notation (e.g. 'data.amount').

        Key lookup is case-insensitive so rule field "Amount" matches
        parsed key "amount" from natural language input.
        """
        parts = field_path.strip().split(".")
        current = data
        for part in parts:
            if not isinstance(current, dict):
                return None
            # Exact match first, then case-insensitive fallback
            if part in current:
                current = current[part]
            else:
                part_lower = part.lower()
                found = False
                for key in current:
                    if key.lower() == part_lower:
                        current = current[key]
                        found = True
                        break
                if not found:
                    return None
        return current

    def _get_action_names(self) -> list[str]:
        """Return the list of configured action names."""
        names = []
        for row in self.actions or []:
            if isinstance(row, dict) and row.get("action_name"):
                names.append(row["action_name"].strip())
        return names or ["Approve", "Reject"]

    # ── Business Rules evaluation ────────────────────────────────────────────

    def _evaluate_business_rules(self, input_data: dict) -> tuple[bool, str]:
        """Evaluate input against configured business rules.

        Returns:
            (needs_approval, reason) — True if rules say human must review.
        """
        rules = self.business_rules or []
        if not rules:
            return False, "No rules configured"

        results: list[tuple[bool, str]] = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            field_path = rule.get("field_path", "").strip()
            operator = rule.get("operator", "equals").strip().lower()
            expected = rule.get("value", "").strip()
            if not field_path:
                continue

            actual = self._extract_field(input_data, field_path)
            matched = _compare(actual, operator, expected)
            desc = f"{field_path} {operator} {expected}"
            logger.info(f"[HumanApproval] Rule: {desc} | actual={actual!r} | matched={matched}")
            results.append((matched, desc))

        if not results:
            return False, "No valid rules to evaluate"

        match_logic = getattr(self, "match_logic", "Any") or "Any"
        if match_logic == "All":
            needs = all(r[0] for r in results)
        else:
            needs = any(r[0] for r in results)

        matched_rules = [desc for matched, desc in results if matched]
        if needs:
            return True, f"Matched: {', '.join(matched_rules)}"
        return False, "No rules matched"

    # ── AI-Decided evaluation ────────────────────────────────────────────────

    async def _evaluate_ai_decision(self, content: str) -> tuple[bool, str, int]:
        """Ask the connected LLM whether the input needs human approval.

        Returns:
            (needs_approval, reason, confidence) — confidence is 0-100.
        """
        llm = self.evaluation_llm
        if not llm or isinstance(llm, str):
            logger.warning("[HumanApproval] AI-Decided mode but no LLM connected — defaulting to pause")
            return True, "No LLM connected", 50

        rule_desc = getattr(self, "rule_description", "") or ""
        prompt = (
            "You are an approval gate evaluator. Based on the business rules below, "
            "decide whether this content needs human approval.\n\n"
            f"RULES:\n{rule_desc}\n\n"
            f"CONTENT TO EVALUATE:\n{content}\n\n"
            "Respond with JSON only:\n"
            '{"needs_approval": true/false, "confidence": 0-100, "reason": "brief explanation"}\n\n'
            "needs_approval = true if any rule says this content requires human review, false if it can be auto-approved.\n"
            "confidence = how confident you are in your needs_approval decision "
            "(100 = absolutely certain, 0 = completely unsure)."
        )

        try:
            response = await llm.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)
            # Extract JSON from response (LLM may add extra text)
            json_match = re.search(r"\{[^}]+\}", text)
            if json_match:
                parsed = json.loads(json_match.group())
                needs = bool(parsed.get("needs_approval", True))
                reason = parsed.get("reason", "")
                confidence = int(parsed.get("confidence", 50))
                confidence = max(0, min(100, confidence))  # clamp to 0-100
                return needs, reason, confidence
            # Fallback: if response contains "false" or "no", auto-approve
            lower = text.lower()
            if "false" in lower or '"needs_approval": false' in lower:
                return False, "AI decided: auto-approve", 75
            return True, "AI decided: needs approval", 25
        except Exception as err:
            logger.warning(f"[HumanApproval] AI evaluation failed: {err} — defaulting to pause")
            return True, f"AI evaluation error: {err}", 50

    # ── Main output method ───────────────────────────────────────────────────

    async def action_output(self) -> Message | Data:
        """Output method shared by all action handles.

        LangGraph calls this method once for EACH output handle (Approve, Reject, …).
        We must call ``interrupt()`` exactly ONCE per node execution — if we called
        it in every output evaluation, LangGraph's index-based resume matching would
        see a second un-resumed interrupt() on the Reject branch and pause again.

        Strategy: call interrupt() on the very first output evaluation, cache the
        human decision on the component instance, and reuse the cached value for all
        subsequent output evaluations in the same node run.
        """
        action_names = self._get_action_names()
        default_action = action_names[0] if action_names else "Approve"

        # ── Determine decision (interrupt or auto-approve) ────────────────
        if not hasattr(self, "_hitl_decision") or self._hitl_decision is None:
            trigger_mode = getattr(self, "trigger_mode", "Always Pause") or "Always Pause"

            interrupt_value = {
                "question": self.approval_message,
                "context": self._extract_content(),
                "actions": action_names,
                "timeout_seconds": int(self.timeout_seconds or 0),
                "node_id": getattr(self, "_vertex", None) and self._vertex.id or "",
            }

            if trigger_mode == "Business Rules":
                input_dict = self._parse_input_as_dict()
                needs_approval, reason = self._evaluate_business_rules(input_dict)
                if needs_approval:
                    interrupt_value["auto_eval_reason"] = reason
                    logger.info(f"[HumanApproval] Business rules triggered: {reason}")
                    self._hitl_decision = interrupt(interrupt_value)
                else:
                    logger.info(f"[HumanApproval] Auto-approved (rules): {reason}")
                    self.status = f"Auto-approved: {reason}"
                    self._hitl_decision = {
                        "action": default_action,
                        "feedback": f"Auto-approved: {reason}",
                    }

            elif trigger_mode == "AI-Decided":
                content = self._extract_content()
                needs_approval, reason, confidence = await self._evaluate_ai_decision(content)

                if not needs_approval:
                    # AI says no approval needed → auto-approve via first action
                    logger.info(f"[HumanApproval] Auto-approved (AI {confidence}%): {reason}")
                    self.status = f"Auto-approved (AI {confidence}%): {reason}"
                    self._hitl_decision = {
                        "action": default_action,
                        "feedback": f"Auto-approved (AI confidence: {confidence}%): {reason}",
                    }
                else:
                    # AI says approval needed → pause for human review, confidence shown as metadata
                    interrupt_value["auto_eval_reason"] = f"AI confidence: {confidence}% — {reason}"
                    interrupt_value["confidence"] = confidence
                    logger.info(f"[HumanApproval] Human review needed (AI {confidence}%): {reason}")
                    self._hitl_decision = interrupt(interrupt_value)

            else:
                # "Always Pause" — existing behavior
                self._hitl_decision = interrupt(interrupt_value)
        # ──────────────────────────────────────────────────────────────────

        human_decision = self._hitl_decision

        # After resume (or auto-approve), decision contains the response, e.g.:
        #   {"action": "Approve", "feedback": "Looks good"}
        if isinstance(human_decision, dict):
            chosen = human_decision.get("action", default_action)
            feedback = human_decision.get("feedback", "")
        else:
            # Fallback: resume value was a plain string action name
            chosen = str(human_decision)
            feedback = ""

        logger.info(f"[HumanApproval] Decision: {chosen!r} (feedback: {feedback!r})")
        if not self.status or not str(self.status).startswith("Auto"):
            self.status = f"Human chose: {chosen}"

        # Get the name of the output currently being evaluated.
        current_output_name = self._current_output  # set by framework before calling method

        if chosen == current_output_name:
            # This is the chosen branch — stop all other outputs.
            for name in action_names:
                if name != chosen:
                    self.stop(name)

            # Pass through the original input along with optional feedback.
            input_val = self.input_value

            logger.debug(
                f"[HumanApproval] input_val type={type(input_val).__name__}, "
                f"repr={input_val!r:.200}"
            )

            # Create a FRESH Message without the upstream storage id.
            # If we pass through the original Message (which carries an id
            # from ChatInput's send_message()), ChatOutput will treat it as
            # already-stored and skip creating a new AI response message.
            text = ""
            if isinstance(input_val, Message):
                text = input_val.text or ""
            elif isinstance(input_val, Data):
                text = str(input_val.data.get("text", "")) if isinstance(input_val.data, dict) else str(input_val.data)
            elif isinstance(input_val, dict):
                # Checkpoint deserialization may return a plain dict instead
                # of a Message/Data object.  Extract text from it.
                text = str(input_val.get("text", "")) if "text" in input_val else str(input_val)
            elif input_val is not None and input_val != "":
                text = str(input_val)

            # Fallback: if text is still empty after extraction, recover from
            # the original_content that the resume API injected into the
            # decision dict (sourced from interrupt_data["context"]).
            # This handles cases where checkpoint serialization corrupted the
            # upstream result or _resolve_params() couldn't resolve the input.
            if not text.strip() and isinstance(human_decision, dict):
                original = human_decision.get("original_content", "")
                if original:
                    logger.info(
                        f"[HumanApproval] Using original_content fallback: {original!r:.100}"
                    )
                    text = original

            extra_kwargs = {}
            if feedback:
                extra_kwargs["hitl_feedback"] = feedback

            logger.debug(f"[HumanApproval] Passing text to downstream: {text!r:.200}")
            return Message(text=text, **({} if not extra_kwargs else {"additional_kwargs": extra_kwargs}))

        # This branch was not chosen — deactivate it.
        self.stop(current_output_name)
        return Message(text="")

    # ── Dynamic output / build_config hooks ─────────────────────────────────

    def update_outputs(self, frontend_node: dict, field_name: str, field_value: Any) -> dict:
        """Rebuild output handles whenever the actions table changes."""
        if field_name == "actions" and field_value:
            frontend_node["outputs"] = []
            for row in field_value:
                if isinstance(row, dict) and row.get("action_name"):
                    name = row["action_name"].strip()
                    if name:
                        frontend_node["outputs"].append(
                            Output(
                                display_name=name,
                                name=name,
                                method="action_output",
                                group_outputs=True,
                                types=["Message", "Data"],
                            )
                        )
        return frontend_node

    async def update_build_config(
        self,
        build_config: dotdict,
        field_value: Any,
        field_name: str | None = None,
    ) -> dotdict:
        """Show/hide fields based on the selected trigger mode."""
        if field_name == "trigger_mode":
            is_rules = field_value == "Business Rules"
            is_ai = field_value == "AI-Decided"
            show_auto = is_rules or is_ai

            # Business Rules fields
            if "business_rules" in build_config:
                build_config["business_rules"]["show"] = is_rules
                build_config["business_rules"]["advanced"] = not is_rules
            if "match_logic" in build_config:
                build_config["match_logic"]["show"] = is_rules
                build_config["match_logic"]["advanced"] = not is_rules

            # AI-Decided fields
            if "evaluation_llm" in build_config:
                build_config["evaluation_llm"]["show"] = is_ai
                build_config["evaluation_llm"]["advanced"] = not is_ai
            if "rule_description" in build_config:
                build_config["rule_description"]["show"] = is_ai
                build_config["rule_description"]["advanced"] = not is_ai

        return build_config


# ── Rule comparison helper ───────────────────────────────────────────────────

def _compare(actual: Any, operator: str, expected: str) -> bool:
    """Compare an actual value against an expected value using the given operator."""
    if actual is None:
        return False

    actual_str = str(actual).strip()
    expected = expected.strip()

    # Numeric comparisons
    if operator in (">", ">=", "<", "<="):
        try:
            a_num = float(actual_str)
            e_num = float(expected)
        except (ValueError, TypeError):
            return False
        if operator == ">":
            return a_num > e_num
        if operator == ">=":
            return a_num >= e_num
        if operator == "<":
            return a_num < e_num
        if operator == "<=":
            return a_num <= e_num

    # String comparisons
    if operator in ("equals", "equal", "=="):
        return actual_str.lower() == expected.lower()
    if operator in ("not equals", "not equal", "!="):
        return actual_str.lower() != expected.lower()
    if operator == "contains":
        return expected.lower() in actual_str.lower()
    if operator == "starts with":
        return actual_str.lower().startswith(expected.lower())
    if operator == "ends with":
        return actual_str.lower().endswith(expected.lower())
    if operator == "regex":
        try:
            return bool(re.search(expected, actual_str))
        except re.error:
            return False

    # Unknown operator — default to equals
    return actual_str.lower() == expected.lower()
