# TARGET PATH: src/backend/base/agentcore/api/a2a.py
"""A2A Protocol HTTP Endpoints (JSON-RPC 2.0 over HTTP).

This module exposes agents as A2A-compliant agents using JSON-RPC 2.0 protocol,
enabling external agents to discover and invoke agents.

Endpoints:
- GET /api/a2a/{agent_id}/.well-known/agent.json - Agent discovery (public)
- POST /api/a2a/{agent_id}/rpc - JSON-RPC 2.0 execution
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from loguru import logger
from sqlmodel import select

from agentcore.api.utils import DbSession
from agentcore.base.a2a.protocol import TaskStatus
from agentcore.helpers.agent import json_schema_from_agent, load_agent, run_agent
from agentcore.schema.a2a_jsonrpc import (
    A2AAgentCardResponse,
    A2AMessageContent,
    A2ASendParams,
    A2ASendResult,
    A2ATaskInfo,
    A2ATasksCancelResult,
    A2ATasksGetResult,
    JsonRpcError,
    JsonRpcErrorCode,
    JsonRpcRequest,
    JsonRpcResponse,
)
from agentcore.services.a2a.task_store import A2ATaskStore
from agentcore.services.database.models.agent.model import Agent


router = APIRouter(prefix="/a2a", tags=["A2A Protocol"])


# --- Helper Functions ---


async def get_agent_for_user(
    agent_id: str,
    user_id: UUID,
    session: DbSession,
) -> Agent | None:
    """Get an agent by ID, validating user ownership."""
    try:
        agent_uuid = UUID(agent_id)
    except ValueError:
        return None

    stmt = select(Agent).where(Agent.id == agent_uuid).where(Agent.user_id == user_id)
    return (await session.exec(stmt)).first()


async def get_agent_by_id(
    agent_id: str,
    session: DbSession,
) -> Agent | None:
    """Get an agent by ID (no user filtering — for A2A discovery and execution)."""
    try:
        agent_uuid = UUID(agent_id)
    except ValueError:
        return None

    return await session.get(Agent, agent_uuid)


def create_error_response(
    code: JsonRpcErrorCode,
    message: str,
    request_id: str | int | None = None,
    data: Any = None,
) -> JsonRpcResponse:
    """Create a JSON-RPC 2.0 error response."""
    return JsonRpcResponse(
        error=JsonRpcError(code=code.value, message=message, data=data),
        id=request_id,
    )


def create_success_response(
    result: Any,
    request_id: str | int | None = None,
) -> JsonRpcResponse:
    """Create a JSON-RPC 2.0 success response."""
    return JsonRpcResponse(result=result, id=request_id)


# --- Agent Card Endpoint ---


@router.get("/{agent_id}/.well-known/agent.json", response_model=A2AAgentCardResponse)
async def get_agent_card(
    agent_id: str,
    session: DbSession,
) -> A2AAgentCardResponse:
    """Get the A2A Agent Card for an agent.

    No authentication required — agent cards are public discovery endpoints
    per the A2A protocol.
    """
    agent = await get_agent_by_id(agent_id, session)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Generate input schema from agent
    input_schema = None
    try:
        input_schema = json_schema_from_agent(agent)
    except Exception as e:
        logger.warning(f"Failed to generate input schema for agent {agent_id}: {e}")

    return A2AAgentCardResponse(
        name=agent.name,
        description=agent.description or f"Agent: {agent.name}",
        url=f"/api/a2a/{agent_id}/rpc",
        version="1.0",
        capabilities=["text-processing", "flow-execution"],
        input_schema=input_schema,
        supported_methods=["message/send", "tasks/get", "tasks/cancel"],
        authentication={"type": "api_key", "header": "x-api-key"},
        metadata={
            "agent_id": str(agent.id),
        },
    )


# --- JSON-RPC Endpoint ---


@router.post("/{agent_id}/rpc", response_model=JsonRpcResponse)
async def jsonrpc_endpoint(
    agent_id: str,
    request: JsonRpcRequest,
    session: DbSession,
    x_user_id: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> JsonRpcResponse:
    """JSON-RPC 2.0 endpoint for A2A protocol.

    Supported methods:
    - message/send: Execute agent synchronously
    - tasks/get: Get task status
    - tasks/cancel: Cancel a running task

    Authentication: accepts X-User-Id header for internal Agentcore-to-Agentcore
    calls, or x-api-key for external callers.
    """
    # Resolve user_id from header
    user_id = x_user_id
    if not user_id:
        return create_error_response(
            JsonRpcErrorCode.INVALID_PARAMS,
            "X-User-Id header is required for A2A RPC calls",
            request.id,
        )

    # Look up agent by ID
    agent = await get_agent_by_id(agent_id, session)
    if not agent:
        return create_error_response(
            JsonRpcErrorCode.FLOW_NOT_FOUND,
            f"Agent {agent_id} not found",
            request.id,
        )

    method_handlers = {
        "message/send": handle_message_send,
        "tasks/get": handle_tasks_get,
        "tasks/cancel": handle_tasks_cancel,
    }

    handler = method_handlers.get(request.method)
    if not handler:
        return create_error_response(
            JsonRpcErrorCode.METHOD_NOT_FOUND,
            f"Method '{request.method}' not found. Supported: {list(method_handlers.keys())}",
            request.id,
        )

    try:
        result = await handler(
            agent=agent,
            params=request.params or {},
            user_id=user_id,
        )
        return create_success_response(result, request.id)
    except ValueError as e:
        logger.warning(f"Invalid params for {request.method}: {e}")
        return create_error_response(
            JsonRpcErrorCode.INVALID_PARAMS,
            str(e),
            request.id,
        )
    except Exception as e:
        logger.exception(f"Error handling {request.method} for agent {agent_id}")
        return create_error_response(
            JsonRpcErrorCode.INTERNAL_ERROR,
            str(e),
            request.id,
        )


# --- Pre-build Helpers ---


def _topological_sort(graph) -> list[str]:
    """Sort graph vertices in topological order (Kahn's algorithm)."""
    in_degree: dict[str, int] = {}
    successors: dict[str, list[str]] = {}
    for vertex in graph.vertices:
        in_degree[vertex.id] = 0
        successors[vertex.id] = []

    for edge in graph.edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in in_degree and target in in_degree:
            in_degree[target] += 1
            successors[source].append(target)

    queue = [vid for vid, deg in in_degree.items() if deg == 0]
    result: list[str] = []
    while queue:
        vid = queue.pop(0)
        result.append(vid)
        for succ in successors.get(vid, []):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    for vid in in_degree:
        if vid not in result:
            result.append(vid)

    return result


async def _prebuild_dependencies(graph, user_id: str, input_value: str) -> None:
    """Pre-build non-output vertices in topological order.

    When a graph is executed via run_agent() -> arun(), only output vertices
    are built directly. _resolve_params() skips predecessors that have not
    been built yet, so components like ChatOutput crash when they access
    source-component properties on an unbuilt predecessor, resulting in
    outputs=[None].

    This method builds all non-output vertices first so that when arun()
    builds the output vertices, all dependencies are resolved.
    """
    from agentcore.schema.schema import INPUT_FIELD_NAME
    from agentcore.services.deps import get_chat_service, get_settings_service

    chat_service = get_chat_service()
    fallback_to_env_vars = get_settings_service().settings.fallback_to_env_var
    inputs_dict = {INPUT_FIELD_NAME: input_value}

    sorted_ids = _topological_sort(graph)

    for vertex_id in sorted_ids:
        vertex = graph.get_vertex(vertex_id)
        if not vertex or vertex.is_output:
            continue
        try:
            await graph.build_vertex(
                vertex_id=vertex_id,
                user_id=user_id,
                inputs_dict=inputs_dict,
                get_cache=chat_service.get_cache,
                set_cache=chat_service.set_cache,
                fallback_to_env_vars=fallback_to_env_vars,
            )
        except Exception as e:
            logger.warning(f"Error pre-building vertex {vertex_id}: {e}")


# --- Method Handlers ---


async def handle_message_send(
    agent: Agent,
    params: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    """Handle message/send method - execute agent synchronously."""
    try:
        send_params = A2ASendParams(**params)
    except Exception as e:
        raise ValueError(f"Invalid params: {e}") from e

    if send_params.message.type == "text":
        input_value = send_params.message.text or ""
    else:
        import json

        input_value = json.dumps(send_params.message.data) if send_params.message.data else ""

    task_store = A2ATaskStore.get_instance()
    task = await task_store.create_task(
        agent_id=str(agent.id),
        user_id=user_id,
        input_data=input_value,
        session_id=send_params.session_id,
        metadata=send_params.metadata,
    )

    await task_store.update_task(task.id, status=TaskStatus.RUNNING)

    try:
        # Load graph and pre-build non-output vertices so that arun()
        # can resolve all dependencies when building output vertices.
        # initialize_run() sets up the trace context that build_vertex() needs.
        graph = await load_agent(user_id, agent_name=agent.name)
        await graph.initialize_run()
        await _prebuild_dependencies(graph, user_id, input_value)

        run_outputs = await run_agent(
            inputs={"input_value": input_value},
            graph=graph,
            user_id=user_id,
            session_id=send_params.session_id,
        )

        output_text = _extract_output_text(run_outputs)

        await task_store.update_task(
            task.id,
            status=TaskStatus.COMPLETED,
            result=output_text,
        )

        task = await task_store.get_task(task.id)

        return A2ASendResult(
            task=A2ATaskInfo(
                id=task.id,
                status=task.status.value,
                created_at=task.created_at,
                completed_at=task.completed_at,
            ),
            content=A2AMessageContent(type="text", text=output_text),
            artifacts=[],
        ).model_dump()

    except Exception as e:
        await task_store.update_task(
            task.id,
            status=TaskStatus.FAILED,
            error=str(e),
        )
        raise


async def handle_tasks_get(
    agent: Agent,
    params: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    """Handle tasks/get method - get task status."""
    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")

    task_store = A2ATaskStore.get_instance()
    task = await task_store.get_task(task_id)

    if not task:
        raise ValueError(f"Task {task_id} not found")

    if task.agent_id != str(agent.id) or task.user_id != user_id:
        raise ValueError(f"Task {task_id} not found")

    return A2ATasksGetResult(
        task=A2ATaskInfo(
            id=task.id,
            status=task.status.value,
            created_at=task.created_at,
            completed_at=task.completed_at,
        ),
        result=task.result,
        error=task.error,
    ).model_dump()


async def handle_tasks_cancel(
    agent: Agent,
    params: dict[str, Any],
    user_id: str,
) -> dict[str, Any]:
    """Handle tasks/cancel method - cancel a running task."""
    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")

    task_store = A2ATaskStore.get_instance()
    task = await task_store.get_task(task_id)

    if not task:
        raise ValueError(f"Task {task_id} not found")

    if task.agent_id != str(agent.id) or task.user_id != user_id:
        raise ValueError(f"Task {task_id} not found")

    success = await task_store.cancel_task(task_id)

    return A2ATasksCancelResult(
        success=success,
        task_id=task_id,
        message="Task cancelled" if success else "Task could not be cancelled (already completed or failed)",
    ).model_dump()


def _extract_output_text(run_outputs: list) -> str:
    """Extract text output from run_outputs."""
    if not run_outputs:
        return ""

    try:
        first_output = run_outputs[0]

        if hasattr(first_output, "outputs") and first_output.outputs:
            # All outputs None means graph vertex builds failed
            if all(output is None for output in first_output.outputs):
                logger.warning(
                    f"A2A agent execution produced all-null outputs "
                    f"({len(first_output.outputs)} output(s) failed). "
                    f"Inputs were: {first_output.inputs}"
                )
                return ""

            for output in first_output.outputs:
                if output and hasattr(output, "results"):
                    for result_value in output.results.values():
                        if hasattr(result_value, "data"):
                            data = result_value.data
                            if isinstance(data, dict):
                                if "text" in data:
                                    return str(data["text"])
                                if "message" in data:
                                    return str(data["message"])
                            if isinstance(data, str):
                                return data
                        if hasattr(result_value, "text"):
                            return str(result_value.text)
                        if isinstance(result_value, str):
                            return result_value

        return str(first_output)

    except Exception as e:
        logger.warning(f"Error extracting output text: {e}")
        return str(run_outputs)