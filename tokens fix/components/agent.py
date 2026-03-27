import json
import re

from langchain_core.tools import StructuredTool

from agentcore.base.agents.agent import LCToolsAgentNode
from agentcore.base.agents.events import ExceptionWithMessageError
from agentcore.base.models.model_utils import get_model_name
from agentcore.components._helpers.current_date import CurrentDateNode
from agentcore.components._helpers.memory import MemoryNode
from agentcore.components._langchain_utilities.tool_calling import ToolCallingAgentNode
from agentcore.custom.custom_node.node import _get_component_toolkit
from agentcore.field_typing import Tool
from agentcore.io import BoolInput, HandleInput, IntInput, MultilineInput, Output
from agentcore.logging import logger
from agentcore.schema.data import Data
from agentcore.schema.dotdict import dotdict
from agentcore.schema.message import Message


class AgentNode(ToolCallingAgentNode):
    display_name: str = "Worker Node"
    description: str = "Define the agent's instructions, then enter a task to complete using tools."
    icon = "bot"
    beta = False
    name = "Agent"

    inputs = [
        HandleInput(
            name="agent_llm",
            display_name="LLM",
            info="Connect a language model component to the agent.",
            input_types=["LanguageModel"],
            required=True,
        ),
        MultilineInput(
            name="system_prompt",
            display_name="Agent Instructions",
            info="System Prompt: Initial instructions and context provided to guide the agent's behavior.",
            value="You are a helpful assistant that answer questions",
            advanced=False,
        ),
        IntInput(
            name="n_messages",
            display_name="Number of Chat History Messages",
            value=100,
            info="Number of chat history messages to retrieve.",
            advanced=True,
            show=True,
        ),
        *LCToolsAgentNode._base_inputs,
        BoolInput(
            name="add_current_date_tool",
            display_name="Current Date",
            advanced=True,
            info="If true, will add a tool to the agent that returns the current date.",
            value=False,
        ),
    ]
    outputs = [
        Output(name="response", display_name="Response", method="message_response"),
        Output(name="structured_response", display_name="Structured Response", method="json_response", tool_mode=False),
    ]

    async def message_response(self) -> Message:
        try:
            # Get LLM model and validate
            llm_model, display_name = self.get_llm()
            if llm_model is None:
                msg = "No language model selected. Please choose a model to proceed."
                raise ValueError(msg)
            self.model_name = get_model_name(llm_model, display_name=display_name)

            # Get memory data
            self.chat_history = await self.get_memory_data()
            if isinstance(self.chat_history, Message):
                self.chat_history = [self.chat_history]

            # Normalize self.tools to a list
            if self.tools is None or self.tools == "" or (isinstance(self.tools, str) and not self.tools.strip()):
                self.tools = []
            elif isinstance(self.tools, list):
                self.tools = [t for t in self.tools if t is not None and t != ""]
            elif hasattr(self.tools, 'name'):
                self.tools = [self.tools]
            else:
                logger.warning("[AgentNode] Unknown tools type %s, resetting to [].", type(self.tools).__name__)
                self.tools = []

            # Add current date tool if enabled
            if self.add_current_date_tool:
                current_date_tool = (await CurrentDateNode(**self.get_base_args()).to_toolkit()).pop(0)
                if not isinstance(current_date_tool, StructuredTool):
                    msg = "CurrentDateNode must be converted to a StructuredTool"
                    raise TypeError(msg)
                self.tools.append(current_date_tool)

            # note the tools are not required to run the agent, hence the validation removed.

            # Set up and run agent
            self.set(
                llm=llm_model,
                tools=self.tools or [],
                chat_history=self.chat_history,
                input_value=self.input_value,
                system_prompt=self.system_prompt,
            )
            agent = self.create_agent_runnable()
            result = await self.run_agent(agent)

            # Store result for potential JSON output
            self._agent_result = result
            # return result

        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"{type(e).__name__}: {e!s}")
            raise
        except ExceptionWithMessageError as e:
            logger.error(f"ExceptionWithMessageError occurred: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e!s}")
            raise
        else:
            return result

    async def json_response(self) -> Data:
        """Convert agent response to structured JSON Data output."""
        try:
            # Run the regular message response first to get the result
            if not hasattr(self, "_agent_result"):
                await self.message_response()

            result = self._agent_result

            # Extract content from result
            if hasattr(result, "content"):
                content = result.content
            elif hasattr(result, "text"):
                content = result.text
            else:
                content = str(result)
            # Ensure content is always a string
            if not isinstance(content, str):
                content = str(content)

            # Try to parse as JSON
            try:
                json_data = json.loads(content)
                if not isinstance(json_data, dict):
                    json_data = {"result": json_data}
                return Data(data=json_data)
            except (json.JSONDecodeError, TypeError):
                # If it's not valid JSON, try to extract JSON from the content
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    try:
                        json_data = json.loads(json_match.group())
                        return Data(data=json_data)
                    except json.JSONDecodeError:
                        pass

                # If we can't extract JSON, return the raw content as data
                return Data(data={"content": content, "error": "Could not parse as JSON"})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[AgentNode] json_response failed, returning fallback: {e}")
            return Data(data={"error": str(e)})

    async def get_memory_data(self):
        messages = (
            await MemoryNode(**self.get_base_args())
            .set(session_id=self.graph.session_id, order="Ascending", n_messages=self.n_messages)
            .retrieve_messages()
        )
        return [
            message for message in messages if getattr(message, "id", None) != getattr(self.input_value, "id", None)
        ]

    def get_llm(self):
        # Custom mode only - agent_llm should be a connected language model component
        if not isinstance(self.agent_llm, str):
            return self.agent_llm, None
        
        # If it's still a string "Custom", no model is connected
        msg = "No language model connected. Please connect a Language Model component to the agent."
        raise ValueError(msg)

    async def update_build_config(
        self, build_config: dotdict, field_value: str, field_name: str | None = None
    ) -> dotdict:
        # Custom mode only - no provider switching needed
        # Just validate required keys
        if field_name == "agent_llm":
            build_config["agent_llm"]["value"] = field_value
            
        default_keys = [
            "code",
            "_type",
            "agent_llm",
            "tools",
            "input_value",
            "add_current_date_tool",
            "system_prompt",
            "agent_description",
            "max_iterations",
            "handle_parsing_errors",
            "verbose",
        ]
        missing_keys = [key for key in default_keys if key not in build_config]
        if missing_keys:
            msg = f"Missing required keys in build_config: {missing_keys}"
            raise ValueError(msg)
            
        return dotdict({k: v.to_dict() if hasattr(v, "to_dict") else v for k, v in build_config.items()})

    async def _get_tools(self) -> list[Tool]:
        component_toolkit = _get_component_toolkit()
        tools_names = self._build_tools_names()
        agent_description = self.get_tool_description()
        description = f"{agent_description}{tools_names}"
        tools = component_toolkit(component=self).get_tools(
            tool_name="Call_Agent", tool_description=description, callbacks=self.get_langchain_callbacks()
        )
        if hasattr(self, "tools_metadata"):
            tools = component_toolkit(component=self, metadata=self.tools_metadata).update_tools_metadata(tools=tools)
        return tools
