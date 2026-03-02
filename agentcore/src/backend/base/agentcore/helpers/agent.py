from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from pydantic.v1 import BaseModel, Field, create_model
from sqlmodel import select

from agentcore.schema.schema import INPUT_FIELD_NAME
from agentcore.services.database.models.agent.model import Agent, AgentRead
from agentcore.services.deps import get_settings_service, session_scope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agentcore.graph_langgraph import LangGraphAdapter as Graph, LangGraphVertex as Vertex, RunOutputs
    from agentcore.schema.data import Data

INPUT_TYPE_MAP = {
    "ChatInput": {"type_hint": "Optional[str]", "default": '""'},
    "TextInput": {"type_hint": "Optional[str]", "default": '""'},
    "JSONInput": {"type_hint": "Optional[dict]", "default": "{}"},
}


async def list_agents(*, user_id: str | None = None) -> list[Data]:
    if not user_id:
        msg = "Session is invalid"
        raise ValueError(msg)
    try:
        async with session_scope() as session:
            uuid_user_id = UUID(user_id) if isinstance(user_id, str) else user_id
            stmt = select(Agent).where(Agent.user_id == uuid_user_id)
            agents = (await session.exec(stmt)).all()

            return [agent.to_data() for agent in agents]
    except Exception as e:
        msg = f"Error listing agents: {e}"
        raise ValueError(msg) from e


async def load_agent(
    user_id: str, agent_id: str | None = None, agent_name: str | None = None, tweaks: dict | None = None
) -> Graph:
    from agentcore.graph_langgraph import LangGraphAdapter as Graph
    from agentcore.processing.process import process_tweaks

    if not agent_id and not agent_name:
        msg = "Agent ID or Agent Name is required"
        raise ValueError(msg)
    if not agent_id and agent_name:
        agent_id = await find_agent(agent_name, user_id)
        if not agent_id:
            msg = f"Agent {agent_name} not found"
            raise ValueError(msg)

    async with session_scope() as session:
        graph_data = agent.data if (agent := await session.get(Agent, agent_id)) else None
    if not graph_data:
        msg = f"Agent {agent_id} not found"
        raise ValueError(msg)
    if tweaks:
        graph_data = process_tweaks(graph_data=graph_data, tweaks=tweaks)
    return Graph.from_payload(graph_data, agent_id=agent_id, user_id=user_id)


async def find_agent(agent_name: str, user_id: str) -> str | None:
    async with session_scope() as session:
        uuid_user_id = UUID(user_id) if isinstance(user_id, str) else user_id
        stmt = select(Agent).where(Agent.name == agent_name).where(Agent.user_id == uuid_user_id)
        agent = (await session.exec(stmt)).first()
        return agent.id if agent else None


async def run_agent(
    inputs: dict | list[dict] | None = None,
    tweaks: dict | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    output_type: str | None = "chat",
    user_id: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    graph: Graph | None = None,
) -> list[RunOutputs]:
    if user_id is None:
        msg = "Session is invalid"
        raise ValueError(msg)
    if graph is None:
        graph = await load_agent(user_id, agent_id, agent_name, tweaks)
    if run_id:
        graph.set_run_id(UUID(run_id))
    if session_id:
        graph.session_id = session_id
    if user_id:
        graph.user_id = user_id

    if inputs is None:
        inputs = []
    if isinstance(inputs, dict):
        inputs = [inputs]
    inputs_list = []
    inputs_components = []
    types = []
    for input_dict in inputs:
        inputs_list.append({INPUT_FIELD_NAME: cast("str", input_dict.get("input_value"))})
        inputs_components.append(input_dict.get("components", []))
        types.append(input_dict.get("type", "chat"))

    outputs = [
        vertex.id
        for vertex in graph.vertices
        if output_type == "debug"
        or (
            vertex.is_output and (output_type == "any" or output_type in vertex.id.lower())  # type: ignore[operator]
        )
    ]

    fallback_to_env_vars = get_settings_service().settings.fallback_to_env_var

    return await graph.arun(
        inputs_list,
        outputs=outputs,
        inputs_components=inputs_components,
        types=types,
        fallback_to_env_vars=fallback_to_env_vars,
    )


def generate_function_for_agent(
    inputs: list[Vertex], agent_id: str, user_id: str | UUID | None
) -> Callable[..., Awaitable[Any]]:
    """Generate a dynamic agent function based on the given inputs and agent ID.

    Args:
        inputs (List[Vertex]): The list of input vertices for the agent.
        agent_id (str): The ID of the agent.
        user_id (str | UUID | None): The user ID associated with the agent.

    Returns:
        Coroutine: The dynamic agent function.

    Raises:
        None

    Example:
        inputs = [vertex1, vertex2]
        agent_id = "my_agent"
        function = generate_function_for_agent(inputs, agent_id)
        result = function(input1, input2)
    """
    # Prepare function arguments with type hints and default values
    args = [
        (
            f"{input_.display_name.lower().replace(' ', '_')}: {INPUT_TYPE_MAP[input_.base_name]['type_hint']} = "
            f"{INPUT_TYPE_MAP[input_.base_name]['default']}"
        )
        for input_ in inputs
    ]

    # Maintain original argument names for constructing the tweaks dictionary
    original_arg_names = [input_.display_name for input_ in inputs]

    # Prepare a Pythonic, valid function argument string
    func_args = ", ".join(args)

    # Map original argument names to their corresponding Pythonic variable names in the function
    arg_mappings = ", ".join(
        f'"{original_name}": {name}'
        for original_name, name in zip(original_arg_names, [arg.split(":")[0] for arg in args], strict=True)
    )

    func_body = f"""
from typing import Optional
async def agent_function({func_args}):
    tweaks = {{ {arg_mappings} }}
    from agentcore.helpers.agent import run_agent
    from langchain_core.tools import ToolException
    from agentcore.base.agent_processing.utils import build_data_from_result_data, format_agent_output_data
    try:
        run_outputs = await run_agent(
            tweaks={{key: {{'input_value': value}} for key, value in tweaks.items()}},
            agent_id="{agent_id}",
            user_id="{user_id}"
        )
        if not run_outputs:
                return []
        run_output = run_outputs[0]

        data = []
        if run_output is not None:
            for output in run_output.outputs:
                if output:
                    data.extend(build_data_from_result_data(output))
        return format_agent_output_data(data)
    except Exception as e:
        raise ToolException(f'Error running agent: ' + e)
"""

    compiled_func = compile(func_body, "<string>", "exec")
    local_scope: dict = {}
    exec(compiled_func, globals(), local_scope)  # noqa: S102
    return local_scope["agent_function"]


def build_function_and_schema(
    agent_data: Data, graph: Graph, user_id: str | UUID | None
) -> tuple[Callable[..., Awaitable[Any]], type[BaseModel]]:
    """Builds a dynamic function and schema for a given agent.

    Args:
        agent_data (Data): The agent record containing information about the agent.
        graph (Graph): The graph representing the agent.
        user_id (str): The user ID associated with the agent.

    Returns:
        Tuple[Callable, BaseModel]: A tuple containing the dynamic function and the schema.
    """
    agent_id = agent_data.id
    inputs = get_agent_inputs(graph)
    dynamic_agent_function = generate_function_for_agent(inputs, agent_id, user_id=user_id)
    schema = build_schema_from_inputs(agent_data.name, inputs)
    return dynamic_agent_function, schema


def get_agent_inputs(graph: Graph) -> list[Vertex]:
    """Retrieves the agent inputs from the given graph.

    Args:
        graph (Graph): The graph object representing the agent.

    Returns:
        List[Data]: A list of input data, where each record contains the ID, name, and description of the input vertex.
    """
    return [vertex for vertex in graph.vertices if vertex.is_input]


def build_schema_from_inputs(name: str, inputs: list[Vertex]) -> type[BaseModel]:
    """Builds a schema from the given inputs.

    Args:
        name (str): The name of the schema.
        inputs (List[tuple[str, str, str]]): A list of tuples representing the inputs.
            Each tuple contains three elements: the input name, the input type, and the input description.

    Returns:
        BaseModel: The schema model.

    """
    fields = {}
    for input_ in inputs:
        field_name = input_.display_name.lower().replace(" ", "_")
        description = input_.description
        fields[field_name] = (str, Field(default="", description=description))
    return create_model(name, **fields)


def get_arg_names(inputs: list[Vertex]) -> list[dict[str, str]]:
    """Returns a list of dictionaries containing the component name and its corresponding argument name.

    Args:
        inputs (List[Vertex]): A list of Vertex objects representing the inputs.

    Returns:
        List[dict[str, str]]: A list of dictionaries, where each dictionary contains the component name and its
            argument name.
    """
    return [
        {"component_name": input_.display_name, "arg_name": input_.display_name.lower().replace(" ", "_")}
        for input_ in inputs
    ]


async def get_agent_by_id_or_endpoint_name(agent_id_or_name: str, user_id: str | UUID | None = None) -> AgentRead | None:
    async with session_scope() as session:
        try:
            agent_id = UUID(agent_id_or_name)
            agent = await session.get(Agent, agent_id)
        except ValueError:
            # Fallback: try matching by agent name
            stmt = select(Agent).where(Agent.name == agent_id_or_name)
            if user_id:
                uuid_user_id = UUID(user_id) if isinstance(user_id, str) else user_id
                stmt = stmt.where(Agent.user_id == uuid_user_id)
            agent = (await session.exec(stmt)).first()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent identifier {agent_id_or_name} not found")
        return AgentRead.model_validate(agent, from_attributes=True)


async def generate_unique_agent_name(agent_name, user_id, session):
    original_name = agent_name
    n = 1
    while True:
        # Check if a agent with the given name exists
        existing_agent = (
            await session.exec(
                select(Agent).where(
                    Agent.name == agent_name,
                    Agent.user_id == user_id,
                )
            )
        ).first()

        # If no agent with the given name exists, return the name
        if not existing_agent:
            return agent_name

        # If a agent with the name already exists, append (n) to the name and increment n
        agent_name = f"{original_name} ({n})"
        n += 1


def json_schema_from_agent(agent: Agent) -> dict:
    """Generate JSON schema from agent input nodes."""
    from agentcore.graph_langgraph import LangGraphAdapter as Graph

    # Get the agent's data which contains the nodes and their configurations
    agent_data = agent.data or {}

    graph = Graph.from_payload(agent_data)
    input_nodes = [vertex for vertex in graph.vertices if vertex.is_input]

    properties = {}
    required = []
    for node in input_nodes:
        node_data = node.data["node"]
        template = node_data["template"]

        for field_name, field_data in template.items():
            if field_data != "Component" and field_data.get("show", False) and not field_data.get("advanced", False):
                field_type = field_data.get("type", "string")
                properties[field_name] = {
                    "type": field_type,
                    "description": field_data.get("info", f"Input for {field_name}"),
                }
                # Update field_type in properties after determining the JSON Schema type
                if field_type == "str":
                    field_type = "string"
                elif field_type == "int":
                    field_type = "integer"
                elif field_type == "float":
                    field_type = "number"
                elif field_type == "bool":
                    field_type = "boolean"
                else:
                    logger.warning(f"Unknown field type: {field_type} defaulting to string")
                    field_type = "string"
                properties[field_name]["type"] = field_type

                if field_data.get("required", False):
                    required.append(field_name)

    return {"type": "object", "properties": properties, "required": required}
