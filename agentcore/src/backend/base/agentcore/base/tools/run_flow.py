from abc import abstractmethod
from typing import TYPE_CHECKING

from loguru import logger
from typing_extensions import override

from agentcore.src.backend.base.agentcore.custom.custom_node.node import Node, _get_component_toolkit
from agentcore.field_typing import Tool
from agentcore.graph_langgraph import LangGraphAdapter
from agentcore.graph_langgraph import LangGraphVertex
from agentcore.helpers.agent import get_agent_inputs
from agentcore.inputs.inputs import (
    DropdownInput,
    InputTypes,
    MessageInput,
)
from agentcore.schema.data import Data
from agentcore.schema.dataframe import DataFrame
from agentcore.schema.dotdict import dotdict
from agentcore.schema.message import Message
from agentcore.template.field.base import Output

if TYPE_CHECKING:
    from agentcore.base.tools.component_tool import ComponentToolkit


class RunAgentBaseNode(Node):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_tool_output = True

    _base_inputs: list[InputTypes] = [
        DropdownInput(
            name="agent_name_selected",
            display_name="agent Name",
            info="The name of the agent to run.",
            options=[],
            real_time_refresh=True,
            value=None,
        ),
        MessageInput(
            name="session_id",
            display_name="Session ID",
            info="The session ID to run the agent in.",
            value="",
            advanced=True,
        ),
    ]
    _base_outputs: list[Output] = [
        Output(
            name="agent_outputs_data",
            display_name="agent Data Output",
            method="data_output",
            hidden=True,
            group_outputs=True,
            tool_mode=False,  # This output is not intended to be used as a tool, so tool_mode is disabled.
        ),
        Output(
            name="agent_outputs_dataframe",
            display_name="agent Dataframe Output",
            method="dataframe_output",
            hidden=True,
            group_outputs=True,
            tool_mode=False,  # This output is not intended to be used as a tool, so tool_mode is disabled.
        ),
        Output(
            name="agent_outputs_message", group_outputs=True, display_name="agent Message Output", method="message_output"
        ),
    ]
    default_keys = ["code", "_type", "agent_name_selected", "session_id"]
    agent_INPUTS: list[dotdict] = []
    agent_tweak_data: dict = {}

    @abstractmethod
    async def run_agent_with_tweaks(self) -> list[Data]:
        """Run the agent with tweaks."""

    async def data_output(self) -> Data:
        """Return the data output."""
        run_outputs = await self.run_agent_with_tweaks()
        first_output = run_outputs[0]

        if isinstance(first_output, Data):
            return first_output

        # just adaptive output Message
        _, message_result = next(iter(run_outputs[0].outputs[0].results.items()))
        message_data = message_result.data
        return Data(data=message_data)

    async def dataframe_output(self) -> DataFrame:
        """Return the dataframe output."""
        run_outputs = await self.run_agent_with_tweaks()
        first_output = run_outputs[0]

        if isinstance(first_output, DataFrame):
            return first_output

        # just adaptive output Message
        _, message_result = next(iter(run_outputs[0].outputs[0].results.items()))
        message_data = message_result.data
        return DataFrame(data=message_data if isinstance(message_data, list) else [message_data])

    async def message_output(self) -> Message:
        """Return the message output."""
        run_outputs = await self.run_agent_with_tweaks()
        _, message_result = next(iter(run_outputs[0].outputs[0].results.items()))
        if isinstance(message_result, Message):
            return message_result
        if isinstance(message_result, str):
            return Message(text=message_result)
        return Message(text=message_result.data["text"])

    async def get_agent_names(self) -> list[str]:
        agent_data = await self.alist_agents()
        return [agent_data.data["name"] for agent_data in agent_data]

    async def get_agent(self, agent_name_selected: str) -> Data | None:
        # get agent from agent id
        agent_datas = await self.alist_agents()
        for agent_data in agent_datas:
            if agent_data.data["name"] == agent_name_selected:
                return agent_data
        return None

    async def get_graph(self, agent_name_selected: str | None = None) -> LangGraphAdapter:
        if agent_name_selected:
            agent_data = await self.get_agent(agent_name_selected)
            if agent_data:
                return LangGraphAdapter.from_payload(agent_data.data["data"])
            msg = "agent not found"
            raise ValueError(msg)
        # Ensure a Graph is always returned or an exception is raised
        msg = "No valid agent JSON or agent name selected."
        raise ValueError(msg)

    def get_new_fields_from_graph(self, graph: LangGraphAdapter) -> list[dotdict]:
        inputs = get_agent_inputs(graph)
        return self.get_new_fields(inputs)

    def update_build_config_from_graph(self, build_config: dotdict, graph: LangGraphAdapter):
        try:
            # Get all inputs from the graph
            new_fields = self.get_new_fields_from_graph(graph)
            old_fields = self.get_old_fields(build_config, new_fields)
            self.delete_fields(build_config, old_fields)
            build_config = self.add_new_fields(build_config, new_fields)

        except Exception as e:
            msg = "Error updating build config from graph"
            logger.exception(msg)
            raise RuntimeError(msg) from e

    def get_new_fields(self, inputs_vertex: list[LangGraphVertex]) -> list[dotdict]:
        new_fields: list[dotdict] = []

        for vertex in inputs_vertex:
            field_template = vertex.data.get("node", {}).get("template", {})
            field_order = vertex.data.get("node", {}).get("field_order", [])
            if field_order and field_template:
                new_vertex_inputs = [
                    dotdict(
                        {
                            **field_template[input_name],
                            "display_name": vertex.display_name + " - " + field_template[input_name]["display_name"],
                            "name": f"{vertex.id}~{input_name}",
                            "tool_mode": not (field_template[input_name].get("advanced", False)),
                        }
                    )
                    for input_name in field_order
                    if input_name in field_template
                ]
                new_fields += new_vertex_inputs
        return new_fields

    def add_new_fields(self, build_config: dotdict, new_fields: list[dotdict]) -> dotdict:
        """Add new fields to the build_config."""
        for field in new_fields:
            build_config[field["name"]] = field
        return build_config

    def delete_fields(self, build_config: dotdict, fields: dict | list[str]) -> None:
        """Delete specified fields from build_config."""
        if isinstance(fields, dict):
            fields = list(fields.keys())
        for field in fields:
            build_config.pop(field, None)

    def get_old_fields(self, build_config: dotdict, new_fields: list[dotdict]) -> list[str]:
        """Get fields that are in build_config but not in new_fields."""
        return [
            field
            for field in build_config
            if field not in [new_field["name"] for new_field in new_fields] + self.default_keys
        ]

    async def get_required_data(self, agent_name_selected):
        self.agent_data = await self.alist_agents()
        for agent_data in self.agent_data:
            if agent_data.data["name"] == agent_name_selected:
                graph = LangGraphAdapter.from_payload(agent_data.data["data"])
                new_fields = self.get_new_fields_from_graph(graph)
                new_fields = self.update_input_types(new_fields)

                return agent_data.data["description"], [field for field in new_fields if field.get("tool_mode") is True]
        return None

    def update_input_types(self, fields: list[dotdict]) -> list[dotdict]:
        for field in fields:
            if isinstance(field, dict):
                if field.get("input_types") is None:
                    field["input_types"] = []
            elif hasattr(field, "input_types") and field.input_types is None:
                field.input_types = []
        return fields

    @override
    async def _get_tools(self) -> list[Tool]:
        component_toolkit: type[ComponentToolkit] = _get_component_toolkit()
        agent_description, tool_mode_inputs = await self.get_required_data(self.agent_name_selected)
        # # convert list of dicts to list of dotdicts
        tool_mode_inputs = [dotdict(field) for field in tool_mode_inputs]
        return component_toolkit(component=self).get_tools(
            tool_name=f"{self.agent_name_selected}_tool",
            tool_description=(
                f"Tool designed to execute the agent '{self.agent_name_selected}'. agent details: {agent_description}."
            ),
            callbacks=self.get_langchain_callbacks(),
            agent_mode_inputs=tool_mode_inputs,
        )
