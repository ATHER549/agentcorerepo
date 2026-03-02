from __future__ import annotations

import uuid
from ast import literal_eval
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Query
from fastapi_pagination import Params
from loguru import logger
from sqlalchemy import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from agentcore.graph_langgraph import LangGraphAdapter
from agentcore.services.auth.utils import get_current_active_user, get_current_active_user_mcp
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.conversation.model import ConversationTable
from agentcore.services.database.models.transactions.model import TransactionTable
from agentcore.services.database.models.user.model import User
from agentcore.services.database.models.vertex_builds.model import VertexBuildTable
from agentcore.services.deps import get_session, session_scope

if TYPE_CHECKING:
    from agentcore.services.chat.service import ChatService


API_WORDS = ["api", "key", "token"]

MAX_PAGE_SIZE = 50
MIN_PAGE_SIZE = 1

CurrentActiveUser = Annotated[User, Depends(get_current_active_user)]
CurrentActiveMCPUser = Annotated[User, Depends(get_current_active_user_mcp)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


class EventDeliveryType(str, Enum):
    STREAMING = "streaming"
    DIRECT = "direct"
    POLLING = "polling"


def has_api_terms(word: str):
    return "api" in word and ("key" in word or ("token" in word and "tokens" not in word))


def remove_api_keys(agent: dict):
    """Remove api keys from agent data."""
    for node in agent.get("data", {}).get("nodes", []):
        node_data = node.get("data").get("node")
        template = node_data.get("template")
        for value in template.values():
            if isinstance(value, dict) and has_api_terms(value["name"]) and value.get("password"):
                value["value"] = None

    return agent


def strip_sensitive_values_from_agent_data(agent_data: dict | None) -> dict | None:
    """Strip all sensitive/secret values from agent data before saving to DB.

    This removes the value of ANY template field that has `password: True`,
    which covers api_key, secret tokens, credentials, and any other field
    defined with SecretStrInput or marked as a password field.

    Unlike `remove_api_keys` which only targets fields with 'api' + 'key'/'token'
    in their name, this method catches ALL password-flagged fields regardless of name.

    Args:
        agent_data: The agent's `data` dict containing `nodes` and `edges`.

    Returns:
        The sanitized agent data dict with sensitive values set to None.
    """
    if not agent_data or not isinstance(agent_data, dict):
        return agent_data

    for node in agent_data.get("nodes", []):
        node_inner = node.get("data", {})
        node_obj = node_inner.get("node", {})
        template = node_obj.get("template", {})
        for field_name, field_def in template.items():
            if not isinstance(field_def, dict):
                continue
            # Strip value from any field marked as a password/secret
            if field_def.get("password") is True:
                logger.debug(
                    "Stripping sensitive field '%s' from node '%s' before DB save",
                    field_name,
                    node_obj.get("display_name", node.get("id", "unknown")),
                )
                field_def["value"] = None

    return agent_data


def build_input_keys_response(langchain_object, artifacts):
    """Build the input keys response."""
    input_keys_response = {
        "input_keys": dict.fromkeys(langchain_object.input_keys, ""),
        "memory_keys": [],
        "handle_keys": artifacts.get("handle_keys", []),
    }

    # Set the input keys values from artifacts
    for key, value in artifacts.items():
        if key in input_keys_response["input_keys"]:
            input_keys_response["input_keys"][key] = value
    
    if hasattr(langchain_object, "memory") and hasattr(langchain_object.memory, "memory_variables"):
        # Remove memory variables from input keys
        input_keys_response["input_keys"] = {
            key: value
            for key, value in input_keys_response["input_keys"].items()
            if key not in langchain_object.memory.memory_variables
        }
        # Add memory variables to memory_keys
        input_keys_response["memory_keys"] = langchain_object.memory.memory_variables

    if hasattr(langchain_object, "prompt") and hasattr(langchain_object.prompt, "template"):
        input_keys_response["template"] = langchain_object.prompt.template

    return input_keys_response

def format_elapsed_time(elapsed_time: float) -> str:
    """Format elapsed time to a human-readable format coming from perf_counter().

    - Less than 1 second: returns milliseconds
    - Less than 1 minute: returns seconds rounded to 2 decimals
    - 1 minute or more: returns minutes and seconds
    """
    delta = timedelta(seconds=elapsed_time)
    if delta < timedelta(seconds=1):
        milliseconds = round(delta / timedelta(milliseconds=1))
        return f"{milliseconds} ms"

    if delta < timedelta(minutes=1):
        seconds = round(elapsed_time, 2)
        unit = "second" if seconds == 1 else "seconds"
        return f"{seconds} {unit}"

    minutes = delta // timedelta(minutes=1)
    seconds = round((delta - timedelta(minutes=minutes)).total_seconds(), 2)
    minutes_unit = "minute" if minutes == 1 else "minutes"
    seconds_unit = "second" if seconds == 1 else "seconds"
    return f"{minutes} {minutes_unit}, {seconds} {seconds_unit}"


async def _get_agent_name(agent_id: uuid.UUID) -> str:
    async with session_scope() as session:
        agent = await session.get(Agent, agent_id)
        if agent is None:
            msg = f"agent {agent_id} not found"
            raise ValueError(msg)
    return agent.name


async def build_graph_from_data(agent_id: uuid.UUID | str, payload: dict, **kwargs):
    """Build and cache the graph.

    Args:
        agent_id: The agent ID
        payload: The agent payload with nodes and edges
        **kwargs: Additional arguments including:
            - agent_name: Name of the agent
            - user_id: User ID for ownership
            - session_id: Session ID for grouping
            - project_id: Folder ID for observability project grouping
            - project_name: Folder name for observability display

    Returns:
        LangGraphAdapter instance
    """
    from loguru import logger
    # Get agent name
    if "agent_name" not in kwargs:
        agent_name = await _get_agent_name(agent_id if isinstance(agent_id, uuid.UUID) else uuid.UUID(agent_id))
    else:
        agent_name = kwargs["agent_name"]
    str_agent_id = str(agent_id)
    session_id = kwargs.get("session_id") or str_agent_id

    # Extract observability parameters
    project_id = kwargs.get("project_id")
    project_name = kwargs.get("project_name")

    logger.info(f"BUILD_GRAPH_FROM_DATA: Calling LangGraphAdapter.from_payload for agent_id={agent_id}")
    # Build graph using LangGraphAdapter
    graph = LangGraphAdapter.from_payload(
        payload,
        str_agent_id,
        agent_name,
        kwargs.get("user_id"),
        project_id=project_id,
        project_name=project_name,
    )

    for vertex_id in graph.has_session_id_vertices:
        vertex = graph.get_vertex(vertex_id)
        if vertex is None:
            msg = f"Vertex {vertex_id} not found"
            raise ValueError(msg)
        if not vertex.raw_params.get("session_id"):
            vertex.update_raw_params({"session_id": session_id}, overwrite=True)

    graph.session_id = session_id
    await graph.initialize_run()
    return graph


async def build_graph_from_db_no_cache(agent_id: uuid.UUID, session: AsyncSession, **kwargs):
    """Build and cache the graph."""
    from agentcore.services.database.models.folder.model import Folder

    agent: Agent | None = await session.get(Agent, agent_id)
    if not agent or not agent.data:
        msg = "Invalid agent ID"
        raise ValueError(msg)
    kwargs["user_id"] = kwargs.get("user_id") or str(agent.user_id)

    # Pass project_id as project_id for observability tracking
    if agent.project_id:
        kwargs["project_id"] = str(agent.project_id)
        # Try to get folder name for project_name
        try:
            folder = await session.get(Folder, agent.project_id)
            if folder:
                kwargs["project_name"] = folder.name
        except Exception:
            pass  # Folder name is optional

    return await build_graph_from_data(agent_id, agent.data, agent_name=agent.name, **kwargs)


async def build_graph_from_db(agent_id: uuid.UUID, session: AsyncSession, chat_service: ChatService, **kwargs):
    graph = await build_graph_from_db_no_cache(agent_id=agent_id, session=session, **kwargs)
    await chat_service.set_cache(str(agent_id), graph)
    return graph


async def build_and_cache_graph_from_data(
    agent_id: uuid.UUID | str,
    chat_service: ChatService,
    graph_data: dict,
):  # -> LangGraphAdapter | Any:
    """Build and cache the graph.
    
    Args:
        agent_id: The agent ID
        chat_service: Chat service for caching
        graph_data: The agent data
    
    Returns:
        LangGraphAdapter instance
    """
    # Convert agent_id to str if it's UUID
    str_agent_id = str(agent_id) if isinstance(agent_id, uuid.UUID) else agent_id
    graph = LangGraphAdapter.from_payload(graph_data, str_agent_id)

    await chat_service.set_cache(str_agent_id, graph)
    return graph


def format_syntax_error_message(exc: SyntaxError) -> str:
    """Format a SyntaxError message for returning to the frontend."""
    if exc.text is None:
        return f"Syntax error in code. Error on line {exc.lineno}"
    return f"Syntax error in code. Error on line {exc.lineno}: {exc.text.strip()}"


def get_causing_exception(exc: BaseException) -> BaseException:
    """Get the causing exception from an exception."""
    if hasattr(exc, "__cause__") and exc.__cause__:
        return get_causing_exception(exc.__cause__)
    return exc


def format_exception_message(exc: Exception) -> str:
    """Format an exception message for returning to the frontend."""
    # We need to check if the __cause__ is a SyntaxError
    # If it is, we need to return the message of the SyntaxError
    causing_exception = get_causing_exception(exc)
    if isinstance(causing_exception, SyntaxError):
        return format_syntax_error_message(causing_exception)
    return str(exc)


def get_top_level_vertices(graph, vertices_ids):
    """Retrieves the top-level vertices from the given graph based on the provided vertex IDs.

    Args:
        graph (Graph): The graph object containing the vertices.
        vertices_ids (list): A list of vertex IDs.

    Returns:
        list: A list of top-level vertex IDs.

    """
    top_level_vertices = []
    for vertex_id in vertices_ids:
        vertex = graph.get_vertex(vertex_id)
        if vertex.parent_is_top_level:
            top_level_vertices.append(vertex.parent_node_id)
        else:
            top_level_vertices.append(vertex_id)
    return top_level_vertices


def parse_exception(exc):
    """Parse the exception message."""
    if hasattr(exc, "body"):
        return exc.body["message"]
    return str(exc)


def get_suggestion_message(outdated_components: list[str]) -> str:
    """Get the suggestion message for the outdated components."""
    count = len(outdated_components)
    if count == 0:
        return "The agent contains no outdated components."
    if count == 1:
        return (
            "The agent contains 1 outdated component. "
            f"We recommend updating the following component: {outdated_components[0]}."
        )
    components = ", ".join(outdated_components)
    return (
        f"The agent contains {count} outdated components. We recommend updating the following components: {components}."
    )


def parse_value(value: Any, input_type: str) -> Any:
    """Helper function to parse the value based on input type."""
    if value == "":
        return {} if input_type == "DictInput" else value
    if input_type == "IntInput":
        return int(value) if value is not None else None
    if input_type == "FloatInput":
        return float(value) if value is not None else None
    if input_type == "DictInput":
        if isinstance(value, dict):
            return value
        try:
            return literal_eval(value) if value is not None else {}
        except (ValueError, SyntaxError):
            return {}
    return value


async def cascade_delete_agent(session: AsyncSession, agent_id: uuid.UUID) -> None:
    try:

        await session.exec(delete(ConversationTable).where(ConversationTable.agent_id == agent_id))
        await session.exec(delete(TransactionTable).where(TransactionTable.agent_id == agent_id))
        await session.exec(delete(VertexBuildTable).where(VertexBuildTable.agent_id == agent_id))
        await session.exec(delete(Agent).where(Agent.id == agent_id))
    except Exception as e:
        msg = f"Unable to cascade delete agent: {agent_id}"
        raise RuntimeError(msg, e) from e


def custom_params(
    page: int | None = Query(None),
    size: int | None = Query(None),
):
    if page is None and size is None:
        return None
    return Params(page=page or MIN_PAGE_SIZE, size=size or MAX_PAGE_SIZE)


