from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator

from collections.abc import AsyncGenerator
from enum import Enum
from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser, parse_value
from agentcore.api.v1_schemas import (
    ConfigResponse,
    CustomComponentRequest,
    CustomComponentResponse,
    InputValueRequest,
    RunResponse,
    SimplifiedAPIRequest,
    UpdateCustomComponentRequest,
)
from agentcore.custom.custom_node.node import Node
from agentcore.custom.utils import (
    add_code_field_to_build_config,
    build_custom_component_template,
    get_instance_name,
    update_component_build_config,
)
from agentcore.events.event_manager import create_stream_tokens_event_manager
from agentcore.exceptions.api import APIException, InvalidChatInputError
from agentcore.exceptions.serialization import SerializationError
from agentcore.graph_langgraph import RunOutputs
from agentcore.helpers.agent import get_agent_by_id_or_endpoint_name
from agentcore.helpers.user import get_user_by_agent_id_or_endpoint_name
from agentcore.interface.initialize.loading import update_params_with_load_from_db_fields
from agentcore.processing.process import process_tweaks, run_graph_internal
from agentcore.services.auth.utils import api_key_security, get_current_active_user
from agentcore.services.database.models.agent.model import Agent, AgentRead
from agentcore.services.database.models.agent.utils import get_all_webhook_components_in_agent
from agentcore.services.database.models.agent_deployment_uat.model import AgentDeploymentUAT, DeploymentUATStatusEnum
from agentcore.services.database.models.agent_deployment_prod.model import AgentDeploymentProd, DeploymentPRODStatusEnum
from agentcore.services.database.models.user.model import User, UserRead
from agentcore.services.deps import get_settings_service, get_telemetry_service, session_scope
from agentcore.services.telemetry.schema import RunPayload
from agentcore.utils.compression import compress_response
from agentcore.utils.version import get_version_info


if TYPE_CHECKING:
    from agentcore.events.event_manager import EventManager
    from agentcore.services.settings.service import SettingsService

router = APIRouter(tags=["Base"])

# ---------------------------------------------------------------------------
# Environment enum & helper for resolving agent data from dev / uat / prod
# ---------------------------------------------------------------------------

class RunEnvironment(str, Enum):
    """Environment to run the agent from."""
    DEV = "dev"    # Read from `agent` table (draft / live editor version)
    UAT = "uat"    # Read from `agent_deployment_uat` table
    PROD = "prod"  # Read from `agent_deployment_prod` table


async def _resolve_agent_data_for_env(
    agent_id: UUID,
    env: RunEnvironment,
    version: str | None = None,
) -> tuple[dict, AgentDeploymentProd | None, AgentDeploymentUAT | None]:
    """Return the flow JSON (nodes/edges) for the requested environment & version.

    - **dev**  → reads ``agent.data`` directly (current draft). Version is ignored.
    - **uat**  → reads ``agent_deployment_uat.agent_snapshot``.
                 If *version* is given (e.g. "v2"), fetches that exact version.
                 If *version* is None, fetches the latest active PUBLISHED deployment.
    - **prod** → reads ``agent_deployment_prod.agent_snapshot``.
                 Same version-or-latest logic as UAT.

    Returns:
        tuple: (flow_data_dict, prod_deployment_record_or_None, uat_deployment_record_or_None).

    Raises:
        HTTPException 404 if no matching published record is found.
    """
    from sqlalchemy import desc

    async with session_scope() as session:
        if env == RunEnvironment.DEV:
            agent = await session.get(Agent, agent_id)
            if not agent or not agent.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent {agent_id} not found or has no data",
                )
            return agent.data, None, None

        if env == RunEnvironment.UAT:
            stmt = (
                select(AgentDeploymentUAT)
                .where(AgentDeploymentUAT.agent_id == agent_id)
                .where(AgentDeploymentUAT.status == DeploymentUATStatusEnum.PUBLISHED)
            )
            if version is not None:
                stmt = stmt.where(AgentDeploymentUAT.version_number == int(version.lstrip("v")))
            else:
                # No version specified → pick the latest active published deployment
                stmt = stmt.where(AgentDeploymentUAT.is_active == True).order_by(  # noqa: E712
                    desc(AgentDeploymentUAT.version_number)
                )
            record = (await session.exec(stmt)).first()
            if not record:
                detail = (
                    f"No PUBLISHED UAT version '{version}' found for agent {agent_id}"
                    if version
                    else f"No active PUBLISHED UAT deployment found for agent {agent_id}"
                )
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
            return record.agent_snapshot, None, record

        # env == RunEnvironment.PROD
        stmt = (
            select(AgentDeploymentProd)
            .where(AgentDeploymentProd.agent_id == agent_id)
            .where(AgentDeploymentProd.status == DeploymentPRODStatusEnum.PUBLISHED)
        )
        if version is not None:
            stmt = stmt.where(AgentDeploymentProd.version_number == int(version.lstrip("v")))
        else:
            # No version specified → pick the latest active published deployment
            stmt = stmt.where(AgentDeploymentProd.is_active == True).order_by(  # noqa: E712
                desc(AgentDeploymentProd.version_number)
            )
        record = (await session.exec(stmt)).first()
        if not record:
            detail = (
                f"No PUBLISHED PROD version '{version}' found for agent {agent_id}"
                if version
                else f"No active PUBLISHED PROD deployment found for agent {agent_id}"
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        return record.agent_snapshot, record, None

@router.get("/all", dependencies=[Depends(get_current_active_user)])
async def get_all():
    """Retrieve all component types with compression for better performance.

    Returns a compressed response containing all available component types.
    """
    from agentcore.interface.components import get_and_cache_all_types_dict

    try:
        all_types = await get_and_cache_all_types_dict(settings_service=get_settings_service())
        # Return compressed response using our utility function
        return compress_response(all_types)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def validate_input_and_tweaks(input_request: SimplifiedAPIRequest) -> None:
    # If the input_value is not None and the input_type is "chat"
    # then we need to check the tweaks if the ChatInput component is present
    # and if its input_value is not None
    # if so, we raise an error
    if not input_request.tweaks:
        return

    for key, value in input_request.tweaks.items():
        if not isinstance(value, dict):
            continue

        input_value = value.get("input_value")
        if input_value is None:
            continue

        request_has_input = input_request.input_value is not None

        if any(chat_key in key for chat_key in ("ChatInput", "Chat Input")):
            if request_has_input and input_request.input_type == "chat":
                msg = "If you pass an input_value to the chat input, you cannot pass a tweak with the same name."
                raise InvalidChatInputError(msg)

        elif (
            any(text_key in key for text_key in ("TextInput", "Text Input"))
            and request_has_input
            and input_request.input_type == "text"
        ):
            msg = "If you pass an input_value to the text input, you cannot pass a tweak with the same name."
            raise InvalidChatInputError(msg)


async def simple_run_agent(
    agent: Agent,
    input_request: SimplifiedAPIRequest,
    *,
    stream: bool = False,
    api_key_user: User | None = None,
    event_manager: EventManager | None = None,
    prod_deployment: AgentDeploymentProd | None = None,
    uat_deployment: AgentDeploymentUAT | None = None,
):
    validate_input_and_tweaks(input_request)
    try:
        from agentcore.api.utils import build_graph_from_data

        task_result: list[RunOutputs] = []
        user_id = api_key_user.id if api_key_user else None
        agent_id_str = str(agent.id)
        if agent.data is None:
            msg = f"agent {agent_id_str} has no data"
            raise ValueError(msg)
        graph_data = agent.data.copy()
        graph_data = process_tweaks(graph_data, input_request.tweaks or {}, stream=stream)
        # Build graph using LangGraph
        graph = await build_graph_from_data(
            agent_id=agent_id_str,
            payload=graph_data,
            user_id=str(user_id) if user_id else None,
            agent_name=agent.name,
        )

        # Set PROD deployment context so adapter logs to transaction_prod
        if prod_deployment is not None:
            graph.prod_deployment_id = str(prod_deployment.id)
            graph.prod_org_id = str(prod_deployment.org_id) if prod_deployment.org_id else None
            graph.prod_dept_id = str(prod_deployment.dept_id) if prod_deployment.dept_id else None

        # Set UAT deployment context so adapter logs to transaction_uat
        if uat_deployment is not None:
            graph.uat_deployment_id = str(uat_deployment.id)
            graph.uat_org_id = str(uat_deployment.org_id) if uat_deployment.org_id else None
            graph.uat_dept_id = str(uat_deployment.dept_id) if uat_deployment.dept_id else None

        inputs = None
        if input_request.input_value is not None:
            inputs = [
                InputValueRequest(
                    components=[],
                    input_value=input_request.input_value,
                    type=input_request.input_type,
                )
            ]
        if input_request.output_component:
            outputs = [input_request.output_component]
        else:
            outputs = [
                vertex.id
                for vertex in graph.vertices
                if input_request.output_type == "debug"
                or (
                    vertex.is_output
                    and (input_request.output_type == "any" or input_request.output_type in vertex.id.lower())  # type: ignore[operator]
                )
            ]
        task_result, session_id = await run_graph_internal(
            graph=graph,
            agent_id=agent_id_str,
            session_id=input_request.session_id,
            inputs=inputs,
            outputs=outputs,
            stream=stream,
            event_manager=event_manager,
        )

        return RunResponse(outputs=task_result, session_id=session_id)

    except sa.exc.StatementError as exc:
        raise ValueError(str(exc)) from exc


async def simple_run_agent_task(
    agent: Agent,
    input_request: SimplifiedAPIRequest,
    *,
    stream: bool = False,
    api_key_user: User | None = None,
    event_manager: EventManager | None = None,
    prod_deployment: AgentDeploymentProd | None = None,
    uat_deployment: AgentDeploymentUAT | None = None,
):
    """Run a agent task as a BackgroundTask, therefore it should not throw exceptions."""
    try:
        return await simple_run_agent(
            agent=agent,
            input_request=input_request,
            stream=stream,
            api_key_user=api_key_user,
            event_manager=event_manager,
            prod_deployment=prod_deployment,
            uat_deployment=uat_deployment,
        )

    except Exception:  # noqa: BLE001
        logger.exception(f"Error running agent {agent.id} task")


async def consume_and_yield(queue: asyncio.Queue, client_consumed_queue: asyncio.Queue) -> AsyncGenerator:
    """Consumes events from a queue and yields them to the client while tracking timing metrics.

    This coroutine continuously pulls events from the input queue and yields them to the client.
    It tracks timing metrics for how long events spend in the queue and how long the client takes
    to process them.

    Args:
        queue (asyncio.Queue): The queue containing events to be consumed and yielded
        client_consumed_queue (asyncio.Queue): A queue for tracking when the client has consumed events

    Yields:
        The value from each event in the queue

    Notes:
        - Events are tuples of (event_id, value, put_time)
        - Breaks the loop when receiving a None value, signaling completion
        - Tracks and logs timing metrics for queue time and client processing time
        - Notifies client consumption via client_consumed_queue
    """
    while True:
        event_id, value, put_time = await queue.get()
        if value is None:
            break
        get_time = time.time()
        yield value
        get_time_yield = time.time()
        client_consumed_queue.put_nowait(event_id)
        logger.debug(
            f"consumed event {event_id} "
            f"(time in queue, {get_time - put_time:.4f}, "
            f"client {get_time_yield - get_time:.4f})"
        )


async def run_agent_generator(
    agent: Agent,
    input_request: SimplifiedAPIRequest,
    api_key_user: User | None,
    event_manager: EventManager,
    client_consumed_queue: asyncio.Queue,
    prod_deployment: AgentDeploymentProd | None = None,
    uat_deployment: AgentDeploymentUAT | None = None,
) -> None:
    """Executes a agent asynchronously and manages event streaming to the client.

    This coroutine runs a agent with streaming enabled and handles the event lifecycle,
    including success completion and error scenarios.

    Args:
        agent (agent): The agent to execute
        input_request (SimplifiedAPIRequest): The input parameters for the agent
        api_key_user (User | None): Optional authenticated user running the agent
        event_manager (EventManager): Manages the streaming of events to the client
        client_consumed_queue (asyncio.Queue): Tracks client consumption of events
        prod_deployment: Optional PROD deployment record for prod-table logging
        uat_deployment: Optional UAT deployment record for uat-table logging

    Events Generated:
        - "add_message": Sent when new messages are added during agent execution
        - "token": Sent for each token generated during streaming
        - "end": Sent when agent execution completes, includes final result
        - "error": Sent if an error occurs during execution

    Notes:
        - Runs the agent with streaming enabled via simple_run_agent()
        - On success, sends the final result via event_manager.on_end()
        - On error, logs the error and sends it via event_manager.on_error()
        - Always sends a final None event to signal completion
    """
    try:
        result = await simple_run_agent(
            agent=agent,
            input_request=input_request,
            stream=True,
            api_key_user=api_key_user,
            event_manager=event_manager,
            prod_deployment=prod_deployment,
            uat_deployment=uat_deployment,
        )
        event_manager.on_end(data={"result": result.model_dump()})
        await client_consumed_queue.get()
    except (ValueError, InvalidChatInputError, SerializationError) as e:
        logger.error(f"Error running agent: {e}")
        event_manager.on_error(data={"error": str(e)})
    finally:
        await event_manager.queue.put((None, None, time.time))


@router.post("/run/{agent_id_or_name}", response_model=None, response_model_exclude_none=True)
async def simplified_run_agent(
    *,
    background_tasks: BackgroundTasks,
    agent: Annotated[AgentRead | None, Depends(get_agent_by_id_or_endpoint_name)],
    input_request: SimplifiedAPIRequest | None = None,
    stream: bool = False,
    api_key_user: Annotated[UserRead, Depends(api_key_security)],
env: RunEnvironment = Query(
        description="Environment to run the agent from: dev (draft from agent table), uat (agent_deployment_uat), or prod (agent_deployment_prod)",
    ),
    version: str = Query(
        description="Version to run (e.g. 'v1', 'v2'). For env=dev this is ignored but still required.",
    ),
):
    """Executes a specified flow by ID with environment and version selection.

    This endpoint executes a agent identified by ID or name, with options for streaming the response
    and tracking execution metrics. It handles both streaming and non-streaming execution modes.

    Args:
        background_tasks: FastAPI background task manager
        flow: The flow to execute, loaded via dependency
        input_request: Input parameters for the flow
        stream: Whether to stream the response
        api_key_user: Authenticated user from API key
        env: Environment — dev (agent table), uat (publish_uat), prod (publish_prod)
        version: Published version string (e.g. 'v1'). Ignored when env=dev.

    Returns:
        Union[StreamingResponse, RunResponse]

    Raises:
        HTTPException: For agent not found (404) or invalid input (400)
        APIException: For internal execution errors (500)

    Examples:
        POST /run/my-agent?env=dev&version=v1       → runs draft from agent table
        POST /run/my-agent?env=uat&version=v2       → runs UAT published version v2
        POST /run/my-agent?env=prod&version=v3      → runs PROD published version v3

    Notes:
        - Supports both streaming and non-streaming execution modes
        - Tracks execution time and success/failure via telemetry
        - Handles graceful client disconnection in streaming mode
        - Provides detailed error handling with appropriate HTTP status codes
        - In streaming mode, uses EventManager to handle events:
            - "add_message": New messages during execution
            - "token": Individual tokens during streaming
            - "end": Final execution result
    """
    telemetry_service = get_telemetry_service()
    input_request = input_request if input_request is not None else SimplifiedAPIRequest()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    # --- Resolve flow data from the correct environment / version ---
    agent.data, prod_deployment, uat_deployment = await _resolve_agent_data_for_env(
        agent_id=agent.id, env=env, version=version
    )
    start_time = time.perf_counter()

    if stream:
        asyncio_queue: asyncio.Queue = asyncio.Queue()
        asyncio_queue_client_consumed: asyncio.Queue = asyncio.Queue()
        event_manager = create_stream_tokens_event_manager(queue=asyncio_queue)
        main_task = asyncio.create_task(
            run_agent_generator(
                agent=agent,
                input_request=input_request,
                api_key_user=api_key_user,
                event_manager=event_manager,
                client_consumed_queue=asyncio_queue_client_consumed,
                prod_deployment=prod_deployment,
                uat_deployment=uat_deployment,
            )
        )

        async def on_disconnect() -> None:
            logger.debug("Client disconnected, closing tasks")
            main_task.cancel()

        return StreamingResponse(
            consume_and_yield(asyncio_queue, asyncio_queue_client_consumed),
            background=on_disconnect,
            media_type="text/event-stream",
        )

    try:
        result = await simple_run_agent(
            agent=agent,
            input_request=input_request,
            stream=stream,
            api_key_user=api_key_user,
            prod_deployment=prod_deployment,
            uat_deployment=uat_deployment,
        )
        end_time = time.perf_counter()
        background_tasks.add_task(
            telemetry_service.log_package_run,
            RunPayload(
                run_is_webhook=False,
                run_seconds=int(end_time - start_time),
                run_success=True,
                run_error_message="",
            ),
        )

    except ValueError as exc:
        background_tasks.add_task(
            telemetry_service.log_package_run,
            RunPayload(
                run_is_webhook=False,
                run_seconds=int(time.perf_counter() - start_time),
                run_success=False,
                run_error_message=str(exc),
            ),
        )
        if "badly formed hexadecimal UUID string" in str(exc):
            # This means the agent ID is not a valid UUID which means it can't find the agent
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if "not found" in str(exc):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        raise APIException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, exception=exc, agent=agent) from exc
    except InvalidChatInputError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        background_tasks.add_task(
            telemetry_service.log_package_run,
            RunPayload(
                run_is_webhook=False,
                run_seconds=int(time.perf_counter() - start_time),
                run_success=False,
                run_error_message=str(exc),
            ),
        )
        raise APIException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, exception=exc, agent=agent) from exc

    return result


@router.post("/webhook/{agent_id_or_name}", response_model=dict, status_code=HTTPStatus.ACCEPTED)  # noqa: RUF100, FAST003
async def webhook_run_agent(
    agent: Annotated[Agent, Depends(get_agent_by_id_or_endpoint_name)],
    user: Annotated[User, Depends(get_user_by_agent_id_or_endpoint_name)],
    request: Request,
    background_tasks: BackgroundTasks,
    env: RunEnvironment = Query(
        description="Environment to run the agent from: dev (draft), uat, or prod",
    ),
    version: str = Query(
        description="Version to run (e.g. 'v1'). Ignored when env=dev.",
    ),
):
    """Run a agent using a webhook request.

    Args:
        agent (agent, optional): The agent to be executed. Defaults to Depends(get_agent_by_id).
        user (User): The agent user.
        request (Request): The incoming HTTP request.
        background_tasks (BackgroundTasks): The background tasks manager.

    Returns:
        dict: A dictionary containing the status of the task.

    Raises:
        HTTPException: If the agent is not found or if there is an error processing the request.
    """
    telemetry_service = get_telemetry_service()
    start_time = time.perf_counter()
    logger.debug("Received webhook request")
    error_msg = ""

    # Resolve flow data for the requested environment / version
    agent.data, prod_deployment, uat_deployment = await _resolve_agent_data_for_env(
        agent_id=agent.id, env=env, version=version
    )

    try:
        try:
            data = await request.body()
        except Exception as exc:
            error_msg = str(exc)
            raise HTTPException(status_code=500, detail=error_msg) from exc

        if not data:
            error_msg = "Request body is empty. You should provide a JSON payload containing the agent ID."
            raise HTTPException(status_code=400, detail=error_msg)

        try:
            # get all webhook components in the agent
            webhook_components = get_all_webhook_components_in_agent(agent.data)
            tweaks = {}

            for component in webhook_components:
                tweaks[component["id"]] = {"data": data.decode() if isinstance(data, bytes) else data}
            input_request = SimplifiedAPIRequest(
                input_value="",
                input_type="chat",
                output_type="chat",
                tweaks=tweaks,
                session_id=None,
            )

            logger.debug("Starting background task")
            background_tasks.add_task(
                simple_run_agent_task,
                agent=agent,
                input_request=input_request,
                api_key_user=user,
                prod_deployment=prod_deployment,
                uat_deployment=uat_deployment,
            )
        except Exception as exc:
            error_msg = str(exc)
            raise HTTPException(status_code=500, detail=error_msg) from exc
    finally:
        background_tasks.add_task(
            telemetry_service.log_package_run,
            RunPayload(
                run_is_webhook=True,
                run_seconds=int(time.perf_counter() - start_time),
                run_success=not error_msg,
                run_error_message=error_msg,
            ),
        )

    return {"message": "Task started in the background", "status": "in progress"}


# get endpoint to return version of agentcore
@router.get("/version")
async def get_version():
    return get_version_info()


@router.post("/custom_component", status_code=HTTPStatus.OK)
async def custom_component(
    raw_code: CustomComponentRequest,
    user: CurrentActiveUser,
) -> CustomComponentResponse:
    component = Node(_code=raw_code.code)

    built_frontend_node, component_instance = build_custom_component_template(component, user_id=user.id)
    if raw_code.frontend_node is not None:
        built_frontend_node = await component_instance.update_frontend_node(built_frontend_node, raw_code.frontend_node)

    tool_mode: bool = built_frontend_node.get("tool_mode", False)
    if isinstance(component_instance, Node):
        await component_instance.run_and_validate_update_outputs(
            frontend_node=built_frontend_node,
            field_name="tool_mode",
            field_value=tool_mode,
        )
    type_ = get_instance_name(component_instance)
    return CustomComponentResponse(data=built_frontend_node, type=type_)


@router.post("/custom_component/update", status_code=HTTPStatus.OK)
async def custom_component_update(
    code_request: UpdateCustomComponentRequest,
    user: CurrentActiveUser,
):
    """Update an existing custom component with new code and configuration.

    Processes the provided code and template updates, applies parameter changes (including those loaded from the
    database), updates the component's build configuration, and validates outputs. Returns the updated component node as
    a JSON-serializable dictionary.

    Raises:
        HTTPException: If an error occurs during component building or updating.
        SerializationError: If serialization of the updated component node fails.
    """
    try:
        component = Node(_code=code_request.code)
        component_node, cc_instance = build_custom_component_template(
            component,
            user_id=user.id,
        )

        component_node["tool_mode"] = code_request.tool_mode

        if hasattr(cc_instance, "set_attributes"):
            template = code_request.get_template()
            params = {}

            for key, value_dict in template.items():
                if isinstance(value_dict, dict):
                    value = value_dict.get("value")
                    input_type = str(value_dict.get("_input_type"))
                    params[key] = parse_value(value, input_type)

            load_from_db_fields = [
                field_name
                for field_name, field_dict in template.items()
                if isinstance(field_dict, dict) and field_dict.get("load_from_db") and field_dict.get("value")
            ]

            params = await update_params_with_load_from_db_fields(cc_instance, params, load_from_db_fields)
            cc_instance.set_attributes(params)
        updated_build_config = code_request.get_template()
        await update_component_build_config(
            cc_instance,
            build_config=updated_build_config,
            field_value=code_request.field_value,
            field_name=code_request.field,
        )
        if "code" not in updated_build_config:
            updated_build_config = add_code_field_to_build_config(updated_build_config, code_request.code)
        component_node["template"] = updated_build_config

        if isinstance(cc_instance, Node):
            await cc_instance.run_and_validate_update_outputs(
                frontend_node=component_node,
                field_name=code_request.field,
                field_value=code_request.field_value,
            )

    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return jsonable_encoder(component_node)
    except Exception as exc:
        raise SerializationError.from_exception(exc, data=component_node) from exc


@router.get("/config")
async def get_config() -> ConfigResponse:
    """Retrieve the current application configuration settings.

    Returns:
        ConfigResponse: The configuration settings of the application.

    Raises:
        HTTPException: If an error occurs while retrieving the configuration.
    """
    try:
        settings_service: SettingsService = get_settings_service()
        return ConfigResponse.from_settings(settings_service.settings)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
