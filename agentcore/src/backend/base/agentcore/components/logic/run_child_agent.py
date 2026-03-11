
"""Run a Child Agent component.

This component enables one agent to call another agent as a "child agent",
with A2A protocol-based communication for tracking and logging.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger

from agentcore.base.child_agent.adapter import ChildAgentAdapter, ChildAgentResult, ParentAgentContext
from agentcore.base.child_agent.guards import (
    ChildAgentCallGuard,
    CircularAgentCallError,
    MaxCallDepthError,
)
from agentcore.base.child_agent.registry import ChildAgentRegistry
from agentcore.custom.custom_node.node import Node
from agentcore.io import (
    BoolInput,
    DropdownInput,
    HandleInput,
    MessageInput,
    Output,
    StrInput,
)
from agentcore.schema.data import Data
from agentcore.schema.dotdict import dotdict
from agentcore.schema.message import Message


class RunChildAgentComponent(Node):
    """Execute another agent as a child agent.

    This component allows a parent agent to call another agent as a child,
    with A2A protocol-based communication for cross-agent communication.
    The child agent executes and returns its output to the parent.

    Features:
    - Select any agent in the project as a child agent
    - Pass any input (text, JSON, agent output, etc.) to the child agent
    - Receive the child agent's output for further processing
    - A2A protocol logging for tracking cross-agent communication
    - Circular call detection to prevent infinite loops
    """

    display_name = "Run a Child Agent"
    description = (
        "Call another agent as a child agent. The child agent receives your input, "
        "executes, and returns its output. Communication uses A2A protocol for tracking."
    )
    icon = "GitBranch"
    name = "RunChildAgent"
    beta = False

    inputs = [
        DropdownInput(
            name="child_agent_name",
            display_name="Child Agent",
            info="Select the agent to run as a child agent.",
            options=[],
            real_time_refresh=True,
            refresh_button=True,
            value=None,
        ),
        HandleInput(
            name="input_value",
            display_name="Input",
            info="Input to pass to the child agent. Can be text, JSON, or output from another component.",
            input_types=["Message", "Data", "str"],
            required=True,
        ),
        StrInput(
            name="session_id",
            display_name="Session ID",
            info="Optional: Share session context with child agent. Leave empty to use parent's session.",
            value="",
            advanced=True,
        ),
        BoolInput(
            name="enable_a2a_logging",
            display_name="Enable A2A Logging",
            value=True,
            info="Log A2A messages between parent and child agent for debugging.",
            advanced=True,
        ),
        StrInput(
            name="log_directory",
            display_name="Log Directory",
            info="Directory to save A2A conversation logs. Each conversation gets a separate timestamped file.",
            value="a2a_logs",
            advanced=True,
        ),
        MessageInput(
            name="max_call_depth",
            display_name="Max Call Depth",
            info="Maximum depth of nested child agent calls (prevents infinite recursion).",
            value="10",
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            name="child_output",
            display_name="Child Agent Output",
            method="run_child_agent",
        ),
        Output(
            name="child_output_data",
            display_name="Child Agent Data Output",
            method="run_child_agent_data",
            hidden=True,
        ),
        Output(
            name="a2a_conversation_log",
            display_name="A2A Conversation Log",
            method="get_a2a_log",
            advanced=True,
        ),
    ]

    # Cache for storing the result after first execution
    _cached_result: ChildAgentResult | None = None

    async def update_build_config(
        self, build_config: dotdict, field_value: Any, field_name: str | None = None
    ):
        """Update build config when child agent is selected."""
        if field_name == "child_agent_name":
            # Get available agents for dropdown
            build_config["child_agent_name"]["options"] = await self._get_available_agents()
        return build_config

    async def _get_available_agents(self) -> list[str]:
        """Get list of available agents for the dropdown."""
        try:
            # Get the current agent ID to exclude it
            current_agent_id = None
            if hasattr(self, "graph") and self.graph:
                current_agent_id = getattr(self.graph, "agent_id", None) or getattr(self.graph, "flow_id", None)

            agent_names = await ChildAgentRegistry.get_agent_names(
                user_id=str(self.user_id),
                exclude_agent_id=current_agent_id,
            )
            return agent_names
        except Exception as e:
            logger.warning(f"Error getting available agents: {e}")
            return []

    def _get_input_text(self) -> str:
        """Extract text from the input value."""
        input_val = self.input_value

        if input_val is None:
            return ""

        if isinstance(input_val, Message):
            return input_val.text or ""

        if isinstance(input_val, Data):
            # Try to get text from data
            if hasattr(input_val, "data") and isinstance(input_val.data, dict):
                return input_val.data.get("text", str(input_val.data))
            return str(input_val)

        if isinstance(input_val, dict):
            return json.dumps(input_val)

        return str(input_val)

    def _build_parent_context(self) -> ParentAgentContext:
        """Build the parent context for the child agent call."""
        parent_agent_id = ""
        parent_agent_name = ""

        if hasattr(self, "graph") and self.graph:
            parent_agent_id = getattr(self.graph, "agent_id", "") or getattr(self.graph, "flow_id", "") or ""
            parent_agent_name = getattr(self.graph, "agent_name", "") or getattr(self.graph, "flow_name", "") or ""

        # Get current call depth from guard
        guard = ChildAgentCallGuard()
        call_depth = guard.get_call_depth()

        return ParentAgentContext(
            parent_agent_id=str(parent_agent_id),
            parent_agent_name=parent_agent_name,
            session_id=self.session_id if self.session_id else getattr(self.graph, "session_id", None),
            call_depth=call_depth,
            a2a_task_id=str(uuid4()),
        )

    async def _execute_child_agent(self) -> ChildAgentResult:
        """Execute the child agent and return the result."""
        # Return cached result if available
        if self._cached_result is not None:
            return self._cached_result

        child_agent_name = self.child_agent_name
        if not child_agent_name:
            return ChildAgentResult(
                output="",
                status="error",
                error="No child agent selected",
            )

        # Get input text
        input_text = self._get_input_text()

        # Build parent context
        parent_context = self._build_parent_context()

        # Create guard with configured max depth
        try:
            max_depth = int(self.max_call_depth) if self.max_call_depth else 10
        except (ValueError, TypeError):
            max_depth = 10
        guard = ChildAgentCallGuard(max_depth=max_depth)

        try:
            # Create adapter for child agent
            adapter = await ChildAgentAdapter.from_agent_name(
                agent_name=child_agent_name,
                user_id=str(self.user_id),
                guard=guard,
            )

            # Execute child agent
            result = await adapter.execute(
                input_value=input_text,
                parent_context=parent_context,
                session_id=self.session_id if self.session_id else None,
            )

            # Log if enabled
            if self.enable_a2a_logging:
                self._log_a2a_messages(result)

            # Cache the result
            self._cached_result = result
            return result

        except CircularAgentCallError as e:
            logger.error(f"Circular agent call detected: {e}")
            return ChildAgentResult(
                output="",
                status="error",
                error=f"Circular agent call detected: {e}",
            )

        except MaxCallDepthError as e:
            logger.error(f"Max call depth exceeded: {e}")
            return ChildAgentResult(
                output="",
                status="error",
                error=f"Maximum call depth exceeded: {e}",
            )

        except Exception as e:
            logger.exception(f"Error executing child agent: {e}")
            return ChildAgentResult(
                output="",
                status="error",
                error=str(e),
            )

    def _log_a2a_messages(self, result: ChildAgentResult) -> None:
        """Log A2A messages for debugging and save to file."""
        if not result.a2a_messages:
            return

        # Log to console
        logger.info(f"A2A Conversation Log for child agent '{self.child_agent_name}':")
        for msg in result.a2a_messages:
            logger.info(
                f"  [{msg.message_type.value}] {msg.sender_id} -> {msg.receiver_id}: "
                f"{msg.content[:100]}{'...' if len(msg.content) > 100 else ''}"
            )

        # Save to file
        self._save_a2a_log_to_file(result)

    def _save_a2a_log_to_file(self, result: ChildAgentResult) -> None:
        """Save the A2A conversation log to a timestamped JSON file."""
        try:
            # Get the log directory (default: a2a_logs)
            log_dir = Path(getattr(self, "log_directory", "a2a_logs"))

            # Create the directory if it doesn't exist
            log_dir.mkdir(parents=True, exist_ok=True)

            # Generate timestamped filename
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"child_agent_a2a_log_{timestamp}.json"
            log_path = log_dir / filename

            # Build log data
            parent_context = self._build_parent_context()
            log_data = {
                "type": "child_agent_communication",
                "parent_agent": {
                    "id": parent_context.parent_agent_id,
                    "name": parent_context.parent_agent_name,
                },
                "child_agent": {
                    "name": self.child_agent_name,
                },
                "status": result.status,
                "execution_time_ms": result.execution_time_ms,
                "messages": [
                    {
                        "id": msg.id,
                        "task_id": msg.task_id,
                        "sender": msg.sender_id,
                        "receiver": msg.receiver_id,
                        "type": msg.message_type.value,
                        "content": msg.content,
                        "timestamp": msg.timestamp.isoformat(),
                        "artifacts": msg.artifacts,
                    }
                    for msg in result.a2a_messages
                ],
                "saved_at": datetime.now().isoformat(),
            }

            with open(log_path, "w") as f:
                json.dump(log_data, f, indent=2)
            logger.info(f"Child agent A2A conversation log saved to: {log_path.absolute()}")
        except Exception as e:
            logger.warning(f"Failed to save child agent A2A log: {e}")

    async def run_child_agent(self) -> Message:
        """Run the child agent and return output as Message.

        Returns:
            Message containing the child agent's output
        """
        result = await self._execute_child_agent()

        if result.status == "error":
            return Message(
                text=f"Error: {result.error}",
                sender="RunChildAgent",
                sender_name="Run a Child Agent",
            )

        return Message(
            text=result.output,
            sender="RunChildAgent",
            sender_name=f"Child Agent: {self.child_agent_name}",
            content_blocks=result.content_blocks or [],
        )

    async def run_child_agent_data(self) -> Data:
        """Run the child agent and return output as Data.

        Returns:
            Data containing the child agent's output and metadata
        """
        result = await self._execute_child_agent()

        return Data(
            data={
                "output": result.output,
                "status": result.status,
                "error": result.error,
                "execution_time_ms": result.execution_time_ms,
                "child_agent_name": self.child_agent_name,
            }
        )

    async def get_a2a_log(self) -> Data:
        """Get the A2A conversation log.

        Returns:
            Data containing the A2A conversation log
        """
        result = await self._execute_child_agent()

        # Build conversation log
        log_data = {
            "parent_agent": {
                "id": self._build_parent_context().parent_agent_id,
                "name": self._build_parent_context().parent_agent_name,
            },
            "child_agent": {
                "name": self.child_agent_name,
            },
            "status": result.status,
            "execution_time_ms": result.execution_time_ms,
            "messages": [
                {
                    "id": msg.id,
                    "task_id": msg.task_id,
                    "sender": msg.sender_id,
                    "receiver": msg.receiver_id,
                    "type": msg.message_type.value,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in result.a2a_messages
            ],
            "timestamp": datetime.now().isoformat(),
        }

        return Data(data=log_data)
