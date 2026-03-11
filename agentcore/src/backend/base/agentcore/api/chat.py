from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import StreamingResponse
from loguru import logger

from agentcore.api.build import (
    cancel_agent_build,
    get_agent_events_response,
    start_agent_build,
)
from agentcore.api.limited_background_tasks import LimitVertexBuildBackgroundTasks
from agentcore.api.utils import (
    CurrentActiveUser,
    DbSession,
    EventDeliveryType,
    build_and_cache_graph_from_data,
    build_graph_from_db,
    get_top_level_vertices,
)
from agentcore.api.v1_schemas import (
    CancelAgentResponse,
    AgentDataRequest,
    InputValueRequest,
    VerticesOrderResponse,
)
from agentcore.exceptions.component import ComponentBuildError
from agentcore.graph_langgraph import log_vertex_build
from agentcore.schema.schema import OutputValue
from agentcore.services.cache.utils import CacheMiss
from agentcore.services.chat.service import ChatService
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.deps import (
    get_chat_service,
    get_queue_service,
    get_session,
    get_telemetry_service,
    session_scope,
)
from agentcore.services.job_queue.service import JobQueueNotFoundError, JobQueueService
from agentcore.services.telemetry.schema import ComponentPayload, PlaygroundPayload

if TYPE_CHECKING:
    from agentcore.graph_langgraph import LangGraphVertex as InterfaceVertex

router = APIRouter(tags=["Chat"])


@router.post("/build/{agent_id}/vertices")
async def retrieve_vertices_order(
    *,
    agent_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    data: Annotated[AgentDataRequest | None, Body(embed=True)] | None = None,
    stop_component_id: str | None = None,
    start_component_id: str | None = None,
    session: DbSession,
) -> VerticesOrderResponse:
    """Retrieve the vertices order for a given agent.

    Args:
        agent_id (str): The ID of the agent.
        background_tasks (BackgroundTasks): The background tasks.
        data (Optional[AgentDataRequest], optional): The agent data. Defaults to None.
        stop_component_id (str, optional): The ID of the stop component. Defaults to None.
        start_component_id (str, optional): The ID of the start component. Defaults to None.
        session (AsyncSession, optional): The session dependency.

    Returns:
        VerticesOrderResponse: The response containing the ordered vertex IDs and the run ID.

    Raises:
        HTTPException: If there is an error checking the build status.
    """
    chat_service = get_chat_service()
    telemetry_service = get_telemetry_service()
    start_time = time.perf_counter()
    components_count = None
    try:
        # First, we need to check if the agent_id is in the cache
        if not data:
            graph = await build_graph_from_db(agent_id=agent_id, session=session, chat_service=chat_service)
        else:
            graph = await build_and_cache_graph_from_data(
                agent_id=agent_id, graph_data=data.model_dump(), chat_service=chat_service
            )
        graph = graph.prepare(stop_component_id, start_component_id)

        # Now vertices is a list of lists
        # We need to get the id of each vertex
        # and return the same structure but only with the ids
        components_count = len(graph.vertices)
        vertices_to_run = list(graph.vertices_to_run.union(get_top_level_vertices(graph, graph.vertices_to_run)))
        await chat_service.set_cache(str(agent_id), graph)
        background_tasks.add_task(
            telemetry_service.log_package_playground,
            PlaygroundPayload(
                playground_seconds=int(time.perf_counter() - start_time),
                playground_component_count=components_count,
                playground_success=True,
            ),
        )
        return VerticesOrderResponse(ids=graph.first_layer, run_id=graph.run_id, vertices_to_run=vertices_to_run)
    except Exception as exc:
        background_tasks.add_task(
            telemetry_service.log_package_playground,
            PlaygroundPayload(
                playground_seconds=int(time.perf_counter() - start_time),
                playground_component_count=components_count,
                playground_success=False,
                playground_error_message=str(exc),
            ),
        )
        if "stream or streaming set to True" in str(exc):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        logger.exception("Error checking build status")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/build/{agent_id}/agent")
async def build_agent(
    *,
    agent_id: uuid.UUID,
    background_tasks: LimitVertexBuildBackgroundTasks,
    inputs: Annotated[InputValueRequest | None, Body(embed=True)] = None,
    data: Annotated[AgentDataRequest | None, Body(embed=True)] = None,
    files: list[str] | None = None,
    stop_component_id: str | None = None,
    start_component_id: str | None = None,
    log_builds: bool = True,
    current_user: CurrentActiveUser,
    queue_service: Annotated[JobQueueService, Depends(get_queue_service)],
    agent_name: str | None = None,
    event_delivery: EventDeliveryType = EventDeliveryType.POLLING,
):
   
    logger.debug(f"build_agent called: agent_id={agent_id}")
    if files:
        logger.debug(f"Files: {files}")
    # First verify the agent exists
    async with session_scope() as session:
        agent = await session.get(Agent, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with id {agent_id} not found")

    job_id = await start_agent_build(
        agent_id=agent_id,
        background_tasks=background_tasks,
        inputs=inputs,
        data=data,
        files=files,
        stop_component_id=stop_component_id,
        start_component_id=start_component_id,
        log_builds=log_builds,
        current_user=current_user,
        queue_service=queue_service,
        agent_name=agent_name,
    )

    # This is required to support FE tests - we need to be able to set the event delivery to direct
    if event_delivery != EventDeliveryType.DIRECT:
        return {"job_id": job_id}
    return await get_agent_events_response(
        job_id=job_id,
        queue_service=queue_service,
        event_delivery=event_delivery,
    )


@router.get("/build/{job_id}/events")
async def get_build_events(
    job_id: str,
    queue_service: Annotated[JobQueueService, Depends(get_queue_service)],
    *,
    event_delivery: EventDeliveryType = EventDeliveryType.STREAMING,
):
    """Get events for a specific build job."""
    return await get_agent_events_response(
        job_id=job_id,
        queue_service=queue_service,
        event_delivery=event_delivery,
    )


@router.post("/build/{job_id}/cancel", response_model=CancelAgentResponse)
async def cancel_build(
    job_id: str,
    queue_service: Annotated[JobQueueService, Depends(get_queue_service)],
):
    """Cancel a specific build job."""
    try:
        # Cancel the agent build and check if it was successful
        cancellation_success = await cancel_agent_build(job_id=job_id, queue_service=queue_service)

        if cancellation_success:
            # Cancellation succeeded or wasn't needed
            return CancelAgentResponse(success=True, message="Agent build cancelled successfully")
        # Cancellation was attempted but failed
        return CancelAgentResponse(success=False, message="Failed to cancel agent build")
    except asyncio.CancelledError:
        # If CancelledError reaches here, it means the task was not successfully cancelled
        logger.error(f"Failed to cancel agent build for job_id {job_id} (CancelledError caught)")
        return CancelAgentResponse(success=False, message="Failed to cancel agent build")
    except ValueError as exc:
        # Job not found
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except JobQueueNotFoundError as exc:
        logger.error(f"Job not found: {job_id}. Error: {exc!s}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job not found: {exc!s}") from exc
    except Exception as exc:
        # Any other unexpected error
        logger.exception(f"Error cancelling agent build for job_id {job_id}: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
