
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import or_, true
from sqlmodel import col, select

from fastapi.responses import StreamingResponse

from agentcore.api.utils import CurrentActiveUser, DbSession, build_graph_from_data
from agentcore.api.v1_schemas import InputValueRequest, RunResponse
from agentcore.services.database.models.agent.model import Agent
from agentcore.events.event_manager import EventManager, create_default_event_manager
from agentcore.services.database.models.agent_deployment_prod.model import (
    AgentDeploymentProd,
    DeploymentPRODStatusEnum,
    ProdDeploymentVisibilityEnum,
)
from agentcore.services.database.models.agent_deployment_uat.model import (
    AgentDeploymentUAT,
    DeploymentUATStatusEnum,
)
from agentcore.services.database.models.agent_publish_recipient.model import (
    AgentPublishRecipient,
)
from agentcore.services.database.models.user_department_membership.model import (
    UserDepartmentMembership,
)
from agentcore.services.database.models.orch_conversation.model import OrchConversationTable
from agentcore.services.database.models.orch_conversation.crud import (
    orch_add_message,
    orch_delete_session,
    orch_get_active_agent,
    orch_get_messages,
    orch_get_sessions,
    orch_rename_session,
)
from agentcore.services.database.models.orch_transaction.crud import (
    orch_delete_session_transactions,
)
router = APIRouter(prefix="/orchestrator", tags=["Orchestrator"])

class OrchAgentSummary(BaseModel):
    deploy_id: UUID
    agent_id: UUID
    agent_name: str
    agent_description: str | None = None
    version_number: int
    environment: str


class OrchChatRequest(BaseModel):
    session_id: str
    agent_id: UUID | None = None
    deployment_id: UUID | None = None
    input_value: str
    version_number: int | None = None


class OrchMessageResponse(BaseModel):
    id: UUID
    timestamp: str
    sender: str
    sender_name: str
    session_id: str
    text: str
    agent_id: UUID | None = None
    deployment_id: UUID | None = None
    category: str = "message"
    properties: dict | None = None
    content_blocks: list | None = None


class OrchChatResponse(BaseModel):
    session_id: str
    agent_name: str
    message: OrchMessageResponse
    context_reset: bool = False


class OrchSessionSummary(BaseModel):
    session_id: str
    last_timestamp: str | None = None
    preview: str = ""
    active_agent_id: UUID | None = None
    active_deployment_id: UUID | None = None
    active_agent_name: str | None = None



def _best_from_message(msg: Any) -> str | None:
    """Try to pull a human-readable string from a message-like value."""
    if isinstance(msg, dict):
        candidates = [
            msg.get("message"),
            msg.get("text"),
            msg.get("data", {}).get("text") if isinstance(msg.get("data"), dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        # Recurse into nested dict/list values to handle wrappers like {"result": {message_dict}}
        for value in msg.values():
            if isinstance(value, dict | list):
                text = _best_from_message(value)
                if text:
                    return text
    elif isinstance(msg, list):
        for item in msg:
            text = _best_from_message(item)
            if text:
                return text
    if isinstance(msg, str) and msg.strip():
        return msg
    return None


def _extract_text(payload: Any) -> str:
    """Extract a human-readable response from a serialized RunResponse dict."""
    if isinstance(payload, str):
        return payload

    if isinstance(payload, dict):
        outputs = payload.get("outputs") or []
        for run_output in outputs:
            if not isinstance(run_output, dict):
                continue
            for result_entry in run_output.get("outputs") or []:
                if not isinstance(result_entry, dict):
                    continue
                text = (
                    _best_from_message(result_entry.get("results"))
                    or _best_from_message(result_entry.get("outputs"))
                    or _best_from_message(result_entry.get("messages"))
                )
                if text:
                    return text
        # Fallback: search all top-level values (skip session_id which is a UUID, not a response)
        for key, value in payload.items():
            if key == "session_id":
                continue
            text = _best_from_message(value)
            if text:
                return text

    if isinstance(payload, list):
        for item in payload:
            text = _extract_text(item)
            if text:
                return text

    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(payload)


async def _lookup_agent_project(session, agent_id: UUID) -> tuple[str | None, str | None]:
    """Look up the agent's project_id and project_name for observability metadata."""
    try:
        agent = await session.get(Agent, agent_id)
        if agent and agent.project_id:
            project_id = str(agent.project_id)
            project_name = None
            try:
                from agentcore.services.database.models.folder.model import Folder
                folder = await session.get(Folder, agent.project_id)
                if folder:
                    project_name = folder.name
            except Exception:
                pass
            return project_id, project_name
    except Exception:
        pass
    return None, None


async def _build_orch_graph(
    *,
    agent_id: str,
    agent_name: str,
    snapshot: dict,
    user_id: str | None,
    session_id: str | None = None,
    deployment_id: str | None = None,
    org_id: str | None = None,
    dept_id: str | None = None,
    stream: bool = False,
    is_prod_deployment: bool = False,
    project_id: str | None = None,
    project_name: str | None = None,
):
    """Build a graph from a published snapshot, ready for execution.

    Returns (graph, inputs, outputs).
    """
    from agentcore.processing.process import process_tweaks
    from agentcore.services.deps import get_chat_service

    graph_data = snapshot.copy()
    graph_data = process_tweaks(graph_data, {}, stream=stream)

    graph = await build_graph_from_data(
        agent_id=agent_id,
        payload=graph_data,
        user_id=user_id,
        agent_name=agent_name,
        session_id=session_id,
        project_id=project_id,
        project_name=project_name,
        chat_service=get_chat_service(),
    )

    # Always update user_id after retrieving the graph — the graph may have
    # been returned from cache with a *different* user's ID. Without this,
    # node-level messages (stored by _store_orch_message) would carry the
    # stale user_id, causing sessions to leak across users.
    graph.user_id = user_id

    if stream:
        for vertex in graph.vertices:
            if isinstance(vertex.template.get("stream"), dict):
                vertex.update_raw_params({"stream": True}, overwrite=True)

    # Orchestration chat persists messages/transactions in its own tables.
    graph.skip_dev_logging = True

    # Tell nodes NOT to persist messages — the orchestrator endpoint stores
    # user messages and agent replies explicitly with correct metadata.
    # Node-level persistence would create duplicates and "Message empty."
    # entries from intermediate nodes (e.g. RegistryModelComponent).
    graph.orch_skip_node_persist = True

    # Pass orch context so the adapter logs to orch_transaction.
    graph.orch_session_id = session_id
    graph.orch_deployment_id = deployment_id
    graph.orch_org_id = org_id
    graph.orch_dept_id = dept_id

    # Set prod/uat deployment context so the adapter tags Langfuse traces
    # with the correct environment ("production" vs "uat").
    if is_prod_deployment:
        graph.prod_deployment_id = deployment_id
        graph.prod_org_id = org_id
        graph.prod_dept_id = dept_id
    else:
        graph.uat_deployment_id = deployment_id
        graph.uat_org_id = org_id
        graph.uat_dept_id = dept_id

    inputs = [
        InputValueRequest(
            components=[],
            input_value="",  # placeholder, set before run
            type="chat",
        )
    ]

    # Prefer ChatOutput vertices; fall back to any output vertex
    outputs = [
        vertex.id
        for vertex in graph.vertices
        if vertex.is_output and "chat" in vertex.id.lower()
    ]
    if not outputs:
        outputs = [vertex.id for vertex in graph.vertices if vertex.is_output]

    return graph, inputs, outputs


def _serialize_content_blocks(content_blocks: list) -> list:
    """Serialize ContentBlock objects to dicts for JSON storage."""
    serialized = []
    for block in content_blocks:
        if hasattr(block, "model_dump"):
            serialized.append(block.model_dump())
        elif isinstance(block, dict):
            serialized.append(block)
    return serialized


def _extract_content_blocks_from_graph(graph) -> list:
    """Extract content_blocks from all built vertices in the graph.

    After graph execution, intermediate vertices (like Agent/Worker Node)
    may contain Messages with tool call content_blocks in their artifacts.
    Output vertices (ChatOutput) typically only have text.
    """
    content_blocks: list = []
    for vertex in graph.vertices:
        if not getattr(vertex, "built", False):
            continue
        artifacts = getattr(vertex, "artifacts", None)
        if artifacts is None:
            continue
        # Direct Message object with content_blocks
        if hasattr(artifacts, "content_blocks") and artifacts.content_blocks:
            content_blocks.extend(artifacts.content_blocks)
        # Dict wrapping a Message
        elif isinstance(artifacts, dict):
            for val in artifacts.values():
                if hasattr(val, "content_blocks") and val.content_blocks:
                    content_blocks.extend(val.content_blocks)
    return content_blocks


async def _run_agent_from_snapshot(
    *,
    agent_id: str,
    agent_name: str,
    snapshot: dict,
    input_value: str,
    session_id: str | None,
    user_id: str | None,
    stream: bool = False,
    event_manager: EventManager | None = None,
    deployment_id: str | None = None,
    org_id: str | None = None,
    dept_id: str | None = None,
    is_prod_deployment: bool = False,
    project_id: str | None = None,
    project_name: str | None = None,
) -> tuple[str, str | None, bool, list]:
    """Build a graph from a published snapshot and run it.

    Returns (response_text, session_id, was_interrupted, content_blocks).
    """
    from agentcore.processing.process import run_graph_internal

    graph, inputs, outputs = await _build_orch_graph(
        agent_id=agent_id,
        agent_name=agent_name,
        snapshot=snapshot,
        user_id=user_id,
        session_id=session_id,
        deployment_id=deployment_id,
        org_id=org_id,
        dept_id=dept_id,
        stream=stream,
        is_prod_deployment=is_prod_deployment,
        project_id=project_id,
        project_name=project_name,
    )

    inputs[0].input_value = input_value

    task_result, result_session_id = await run_graph_internal(
        graph=graph,
        agent_id=agent_id,
        session_id=session_id,
        inputs=inputs,
        outputs=outputs,
        stream=stream,
        event_manager=event_manager,
    )

    # Check if the graph was interrupted (HITL pause)
    was_interrupted = any(
        (getattr(ro, "metadata", None) or {}).get("status") == "interrupted"
        for ro in task_result
    )
    if was_interrupted:
        logger.info(f"[ORCH] Graph interrupted (HITL) — no response text to extract")
        return "", result_session_id, True, []

    # Extract content_blocks (tool calls, etc.) from all built vertices
    content_blocks = _extract_content_blocks_from_graph(graph)

    run_response = RunResponse(outputs=task_result, session_id=result_session_id)
    encoded = jsonable_encoder(run_response)
    logger.debug(f"[ORCH] RunResponse encoded payload: {json.dumps(encoded, default=str)[:2000]}")
    response_text = _extract_text(encoded)
    logger.info(f"[ORCH] Extracted response text: {response_text[:500] if response_text else '(empty)'}")

    return response_text, result_session_id, False, content_blocks



async def _resolve_agent(
    session,
    current_user: CurrentActiveUser,
    body: OrchChatRequest,
) -> tuple[UUID, UUID, AgentDeploymentProd | AgentDeploymentUAT]:
    """Resolve the target agent for a chat request (sticky routing).

    If agent_id/deployment_id are provided → use them (explicit @mention).
    Otherwise → look up the last active agent in the session.
    Raises 400 if no agent can be resolved (new session with no @mention).
    """
    agent_id = body.agent_id
    deployment_id = body.deployment_id

    if not agent_id or not deployment_id:
        active = await orch_get_active_agent(session, body.session_id)
        if active:
            agent_id = agent_id or active["agent_id"]
            deployment_id = deployment_id or active["deployment_id"]
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No agent specified and no active agent in session. Mention an agent with @ to start.",
            )

    deployment = await session.get(AgentDeploymentProd, deployment_id)
    if not deployment:
        deployment = await session.get(AgentDeploymentUAT, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment {deployment_id} not found",
        )

    if not await _user_can_access_deployment(session, current_user, deployment):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this deployment.",
        )

    return agent_id, deployment_id, deployment


async def _user_can_access_deployment(
    session: DbSession,
    current_user: CurrentActiveUser,
    deployment: AgentDeploymentProd | AgentDeploymentUAT,
) -> bool:
    role = str(getattr(current_user, "role", "")).lower()
    if role in {"super_admin", "department_admin", "root"}:
        return True

    if deployment.deployed_by == current_user.id:
        return True

    recipient_exists = (
        await session.exec(
            select(AgentPublishRecipient.id)
            .where(
                AgentPublishRecipient.agent_id == deployment.agent_id,
                AgentPublishRecipient.recipient_user_id == current_user.id,
                or_(
                    deployment.dept_id is None,
                    AgentPublishRecipient.dept_id == deployment.dept_id,
                ),
            )
            .limit(1)
        )
    ).first()
    if recipient_exists:
        return True

    if isinstance(deployment, AgentDeploymentProd):
        visibility_value = (
            deployment.visibility.value
            if hasattr(deployment.visibility, "value")
            else str(deployment.visibility)
        )
        if str(visibility_value).upper() == "PUBLIC":
            member_exists = (
                await session.exec(
                    select(UserDepartmentMembership.id)
                    .where(
                        UserDepartmentMembership.user_id == current_user.id,
                        UserDepartmentMembership.department_id == deployment.dept_id,
                        UserDepartmentMembership.status == "active",
                    )
                    .limit(1)
                )
            ).first()
            if member_exists:
                return True

    return False


async def _maybe_context_reset(
    session,
    *,
    session_id: str,
    new_agent_id: UUID,
    new_agent_name: str,
    user_id: UUID,
    new_deployment_id: UUID,
) -> bool:
    """Insert a context-reset system message if the active agent has changed.

    Returns True if a context reset occurred (agent switched).
    """
    active = await orch_get_active_agent(session, session_id)
    if not active or active["agent_id"] == new_agent_id:
        return False

    reset_ts = datetime.now(timezone.utc).replace(tzinfo=None)
    reset_msg = OrchConversationTable(
        id=uuid4(),
        sender="system",
        sender_name="System",
        session_id=session_id,
        text=f"Switched to {new_agent_name}",
        agent_id=new_agent_id,
        user_id=user_id,
        deployment_id=new_deployment_id,
        timestamp=reset_ts,
        files=[],
        properties={},
        category="context_reset",
        content_blocks=[],
    )
    await orch_add_message(reset_msg, session)
    logger.info(f"[ORCH] Context reset: switched to {new_agent_name} in session {session_id}")
    return True



@router.get("/agents", response_model=list[OrchAgentSummary], status_code=200)
async def list_orch_agents(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Return accessible UAT/PROD deployed agents for orchestration chat."""
    try:
        current_role = str(getattr(current_user, "role", "")).lower()
        is_admin = current_role in {"super_admin", "department_admin", "root"}

        prod_share_exists = (
            select(AgentPublishRecipient.id)
            .where(
                AgentPublishRecipient.agent_id == AgentDeploymentProd.agent_id,
                AgentPublishRecipient.recipient_user_id == current_user.id,
                or_(
                    AgentDeploymentProd.dept_id.is_(None),
                    AgentPublishRecipient.dept_id == AgentDeploymentProd.dept_id,
                ),
            )
            .exists()
        )
        prod_dept_member_exists = (
            select(UserDepartmentMembership.id)
            .where(
                UserDepartmentMembership.user_id == current_user.id,
                UserDepartmentMembership.department_id == AgentDeploymentProd.dept_id,
                UserDepartmentMembership.status == "active",
            )
            .exists()
        )
        prod_private_access = (
            (AgentDeploymentProd.deployed_by == current_user.id)
            | prod_share_exists
        )
        prod_public_access = prod_private_access | prod_dept_member_exists
        if is_admin:
            prod_private_access = prod_private_access | true()
            prod_public_access = prod_public_access | true()

        prod_stmt = (
            select(AgentDeploymentProd)
            .where(AgentDeploymentProd.status == DeploymentPRODStatusEnum.PUBLISHED)
            .where(AgentDeploymentProd.is_active == True)  # noqa: E712
            .where(AgentDeploymentProd.is_enabled == True)  # noqa: E712
            .where(
                (
                    (AgentDeploymentProd.visibility == ProdDeploymentVisibilityEnum.PUBLIC)
                    & prod_public_access
                )
                | (
                    (AgentDeploymentProd.visibility == ProdDeploymentVisibilityEnum.PRIVATE)
                    & prod_private_access
                )
            )
        )

        uat_share_exists = (
            select(AgentPublishRecipient.id)
            .where(
                AgentPublishRecipient.agent_id == AgentDeploymentUAT.agent_id,
                AgentPublishRecipient.recipient_user_id == current_user.id,
                or_(
                    AgentDeploymentUAT.dept_id.is_(None),
                    AgentPublishRecipient.dept_id == AgentDeploymentUAT.dept_id,
                ),
            )
            .exists()
        )
        uat_access = (
            (AgentDeploymentUAT.deployed_by == current_user.id)
            | uat_share_exists
        )
        if is_admin:
            uat_access = uat_access | true()

        uat_stmt = (
            select(AgentDeploymentUAT)
            .where(AgentDeploymentUAT.status == DeploymentUATStatusEnum.PUBLISHED)
            .where(AgentDeploymentUAT.is_active == True)  # noqa: E712
            .where(AgentDeploymentUAT.is_enabled == True)  # noqa: E712
            .where(uat_access)
        )

        prod_records = list((await session.exec(prod_stmt)).all())
        uat_records = list((await session.exec(uat_stmt)).all())

        # Keep all PROD versions. Hide UAT rows only when a PROD exists for same agent_id.
        prod_agent_ids = {str(rec.agent_id) for rec in prod_records}
        filtered_uat_records = [
            rec for rec in uat_records if str(rec.agent_id) not in prod_agent_ids
        ]

        records_with_env: list[tuple[AgentDeploymentProd | AgentDeploymentUAT, str]] = (
            [(rec, "prod") for rec in prod_records]
            + [(rec, "uat") for rec in filtered_uat_records]
        )
        records_with_env.sort(
            key=lambda row: (
                str(row[0].agent_name or "").lower(),
                -int(getattr(row[0], "version_number", 0) or 0),
            )
        )

        return [
            OrchAgentSummary(
                deploy_id=r.id,
                agent_id=r.agent_id,
                agent_name=r.agent_name,
                agent_description=r.agent_description,
                version_number=r.version_number,
                environment=env_name,
            )
            for r, env_name in records_with_env
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing orchestrator agents: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e



@router.post("/chat", response_model=OrchChatResponse, status_code=200)
async def orch_chat(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    body: OrchChatRequest,
):
    """Send a user message to a deployed agent and return the agent's reply.

    Sticky routing: if agent_id/deployment_id are omitted, the message is
    routed to the last active agent in the session.

    Context reset: when the agent changes mid-session, a system message is
    inserted as a divider and the new agent starts with a fresh context.
    """
    try:
        # -- 1. Resolve agent (sticky routing) -----------------------------
        agent_id, deployment_id, deployment = await _resolve_agent(
            session,
            current_user,
            body,
        )

        # -- 2. Context reset if agent switched ----------------------------
        did_reset = await _maybe_context_reset(
            session,
            session_id=body.session_id,
            new_agent_id=agent_id,
            new_agent_name=deployment.agent_name,
            user_id=current_user.id,
            new_deployment_id=deployment_id,
        )

        # -- 3. Persist user message ---------------------------------------
        msg_ts = datetime.now(timezone.utc).replace(tzinfo=None)
        user_msg = OrchConversationTable(
            id=uuid4(),
            sender="user",
            sender_name=current_user.username or "User",
            session_id=body.session_id,
            text=body.input_value,
            agent_id=agent_id,
            user_id=current_user.id,
            deployment_id=deployment_id,
            timestamp=msg_ts,
            files=[],
            properties={},
            category="message",
            content_blocks=[],
        )
        await orch_add_message(user_msg, session)

        # -- 4. Run the agent from its deployment snapshot -------------------
        project_id, project_name = await _lookup_agent_project(session, agent_id)
        logger.info(f"[ORCH] Agent={deployment.agent_name} | session={body.session_id} | input_value={body.input_value!r}")
        agent_text, _, _was_hitl, agent_content_blocks = await _run_agent_from_snapshot(
            agent_id=str(agent_id),
            agent_name=deployment.agent_name,
            snapshot=deployment.agent_snapshot,
            input_value=body.input_value,
            session_id=body.session_id,
            user_id=str(current_user.id),
            deployment_id=str(deployment_id),
            org_id=str(deployment.org_id) if deployment.org_id else None,
            dept_id=str(deployment.dept_id) if deployment.dept_id else None,
            is_prod_deployment=isinstance(deployment, AgentDeploymentProd),
            project_id=project_id,
            project_name=project_name,
        )

        if not agent_text or not agent_text.strip():
            agent_text = "Agent did not produce a response."

        # Serialize content_blocks for storage
        serialized_blocks = _serialize_content_blocks(agent_content_blocks)

        # -- 5. Persist agent reply ----------------------------------------
        reply_ts = datetime.now(timezone.utc).replace(tzinfo=None)
        agent_msg = OrchConversationTable(
            id=uuid4(),
            sender="agent",
            sender_name=deployment.agent_name,
            session_id=body.session_id,
            text=agent_text,
            agent_id=agent_id,
            user_id=current_user.id,
            deployment_id=deployment_id,
            timestamp=reply_ts,
            files=[],
            properties={},
            category="message",
            content_blocks=serialized_blocks,
        )
        saved_agent_msg = await orch_add_message(agent_msg, session)

        return OrchChatResponse(
            session_id=body.session_id,
            agent_name=deployment.agent_name,
            context_reset=did_reset,
            message=OrchMessageResponse(
                id=saved_agent_msg.id,
                timestamp=saved_agent_msg.timestamp.isoformat() if saved_agent_msg.timestamp else "",
                sender="agent",
                sender_name=deployment.agent_name,
                session_id=body.session_id,
                text=agent_text,
                agent_id=agent_id,
                deployment_id=deployment_id,
                content_blocks=serialized_blocks or None,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in orchestrator chat: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/chat/stream", status_code=200)
async def orch_chat_stream(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    body: OrchChatRequest,
):
    """Stream agent response token-by-token as NDJSON events.

    Sticky routing + context reset apply here just like /chat.

    Event types emitted:
      - ``add_message``  – first chunk (UI creates the message bubble)
      - ``token``        – subsequent chunks ``{chunk, id}``
      - ``end``          – signals stream is done, carries final ``{agent_text, message_id}``
    """
    # -- 1. Resolve agent (sticky routing) -------------------------------
    agent_id, deployment_id, deployment = await _resolve_agent(
        session,
        current_user,
        body,
    )

    # -- 2. Context reset if agent switched ------------------------------
    await _maybe_context_reset(
        session,
        session_id=body.session_id,
        new_agent_id=agent_id,
        new_agent_name=deployment.agent_name,
        user_id=current_user.id,
        new_deployment_id=deployment_id,
    )

    # -- 3. Persist user message -----------------------------------------
    stream_msg_ts = datetime.now(timezone.utc).replace(tzinfo=None)
    user_msg = OrchConversationTable(
        id=uuid4(),
        sender="user",
        sender_name=current_user.username or "User",
        session_id=body.session_id,
        text=body.input_value,
        agent_id=agent_id,
        user_id=current_user.id,
        deployment_id=deployment_id,
        timestamp=stream_msg_ts,
        files=[],
        properties={},
        category="message",
        content_blocks=[],
    )
    await orch_add_message(user_msg, session)

    # -- 4. Set up streaming queue + event manager -----------------------
    # Look up project info for observability metadata before entering background task
    orch_project_id, orch_project_name = await _lookup_agent_project(session, agent_id)

    queue: asyncio.Queue = asyncio.Queue()
    event_manager = create_default_event_manager(queue)

    # Capture values needed by the background coroutine
    agent_id_str = str(agent_id)
    agent_name = deployment.agent_name
    snapshot = deployment.agent_snapshot
    input_value = body.input_value
    chat_session_id = body.session_id
    user_id_str = str(current_user.id)
    dep_agent_id = agent_id
    dep_deployment_id = deployment_id
    dep_user_id = current_user.id
    dep_org_id = str(deployment.org_id) if deployment.org_id else None
    dep_dept_id = str(deployment.dept_id) if deployment.dept_id else None
    dep_is_prod = isinstance(deployment, AgentDeploymentProd)

    async def _run_and_persist():
        """Background coroutine: run the agent, persist reply, close the queue."""
        try:
            agent_text, _result_sid, was_interrupted, agent_content_blocks = await _run_agent_from_snapshot(
                agent_id=agent_id_str,
                agent_name=agent_name,
                snapshot=snapshot,
                input_value=input_value,
                session_id=chat_session_id,
                user_id=user_id_str,
                stream=True,
                event_manager=event_manager,
                deployment_id=str(dep_deployment_id),
                org_id=dep_org_id,
                dept_id=dep_dept_id,
                is_prod_deployment=dep_is_prod,
                project_id=orch_project_id,
                project_name=orch_project_name,
            )

            # When interrupted (HITL pause), _emit_hitl_pause_event already
            # emitted the add_message with HITL metadata to the frontend.
            # Do NOT persist an agent reply or emit end with agent_text — that
            # would overwrite the HITL action buttons on the frontend.
            if was_interrupted:
                logger.info(f"[ORCH-STREAM] Run interrupted (HITL) — persisting pause message")
                # Persist the HITL pause message so it survives page navigation.
                # The SSE `add_message` event (from _emit_hitl_pause_event) only
                # lives in the active stream; when the user navigates away and
                # comes back, messages are reloaded from DB.  This row ensures
                # the HITL action buttons reappear for still-pending requests.
                from agentcore.services.deps import session_scope

                try:
                    # Fetch the pending HITL request to get interrupt_data
                    from agentcore.services.database.models.hitl_request.model import HITLRequest, HITLStatus
                    from sqlmodel import col, select as _sel

                    async with session_scope() as db:
                        stmt = (
                            _sel(HITLRequest)
                            .where(HITLRequest.session_id == chat_session_id)
                            .where(HITLRequest.status == HITLStatus.PENDING)
                            .order_by(col(HITLRequest.requested_at).desc())
                            .limit(1)
                        )
                        hitl_row = (await db.exec(stmt)).first()

                    actions = []
                    question = "Awaiting human review"
                    if hitl_row and hitl_row.interrupt_data:
                        idata = hitl_row.interrupt_data
                        actions = idata.get("actions", [])
                        question = idata.get("question", question)

                    actions_display = "\n".join(f"• {a}" for a in actions) if actions else "—"
                    hitl_text = (
                        f"⏸ **Waiting for human review**\n\n"
                        f"{question}\n\n"
                        f"**Available actions:**\n{actions_display}"
                    )

                    hitl_ts = datetime.now(timezone.utc).replace(tzinfo=None)
                    async with session_scope() as db:
                        hitl_msg = OrchConversationTable(
                            id=uuid4(),
                            sender="agent",
                            sender_name=agent_name,
                            session_id=chat_session_id,
                            text=hitl_text,
                            agent_id=dep_agent_id,
                            user_id=dep_user_id,
                            deployment_id=dep_deployment_id,
                            timestamp=hitl_ts,
                            files=[],
                            properties={
                                "hitl": True,
                                "thread_id": chat_session_id,
                                "actions": actions,
                            },
                            category="message",
                            content_blocks=[],
                        )
                        await orch_add_message(hitl_msg, db)
                except Exception as _err:
                    logger.warning(f"[ORCH-STREAM] Could not persist HITL message: {_err}")

                event_manager.on_end(data={})
                return

            if not agent_text or not agent_text.strip():
                agent_text = "Agent did not produce a response."

            # Serialize content_blocks for storage
            serialized_blocks = _serialize_content_blocks(agent_content_blocks)

            # Persist agent reply in orch tables (uses its own DB session)
            from agentcore.services.deps import session_scope

            stream_reply_ts = datetime.now(timezone.utc).replace(tzinfo=None)
            async with session_scope() as db:
                agent_msg = OrchConversationTable(
                    id=uuid4(),
                    sender="agent",
                    sender_name=agent_name,
                    session_id=chat_session_id,
                    text=agent_text,
                    agent_id=dep_agent_id,
                    user_id=dep_user_id,
                    deployment_id=dep_deployment_id,
                    timestamp=stream_reply_ts,
                    files=[],
                    properties={},
                    category="message",
                    content_blocks=serialized_blocks,
                )
                await orch_add_message(agent_msg, db)

            # Signal end with final data so the frontend can finalize
            event_manager.on_end(data={
                "agent_text": agent_text,
                "message_id": str(agent_msg.id),
                "content_blocks": serialized_blocks,
            })
        except Exception as exc:
            logger.exception(f"[ORCH-STREAM] Error: {exc}")
            event_manager.on_error(data={"text": str(exc)})
            event_manager.on_end(data={})
        finally:
            # Sentinel to stop the consumer
            queue.put_nowait((None, None, None))

    # -- 4. Start background task and return streaming response ----------
    run_task = asyncio.create_task(_run_and_persist())

    async def _consume():
        while True:
            try:
                _event_id, value, _ = await queue.get()
                if value is None:
                    break
                yield value
            except Exception:
                break

    async def _on_disconnect():
        run_task.cancel()

    return StreamingResponse(
        _consume(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
        background=_on_disconnect,
    )



@router.get("/sessions", response_model=list[OrchSessionSummary], status_code=200)
async def list_orch_sessions(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Return all orchestrator chat sessions owned by the current user.

    Each session includes the currently active agent (from the most recent message).
    """
    try:
        rows = await orch_get_sessions(session, user_id=current_user.id)
        summaries = []
        for row in rows:
            summary = OrchSessionSummary(**row)
            active = await orch_get_active_agent(session, row["session_id"])
            if active:
                summary.active_agent_id = active["agent_id"]
                summary.active_deployment_id = active["deployment_id"]
                dep = await session.get(AgentDeploymentProd, active["deployment_id"])
                if not dep:
                    dep = await session.get(AgentDeploymentUAT, active["deployment_id"])
                if dep:
                    summary.active_agent_name = dep.agent_name
            summaries.append(summary)
        return summaries
    except Exception as e:
        logger.error(f"Error listing orch sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e




@router.get("/sessions/{session_id}/messages", response_model=list[OrchMessageResponse], status_code=200)
async def get_orch_session_messages(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    session_id: str,
):
    """Return all messages in an orchestrator session ordered by timestamp."""
    try:
        messages = await orch_get_messages(
            session,
            session_id=session_id,
            user_id=current_user.id,
        )
        return [
            OrchMessageResponse(
                id=m.id,
                timestamp=m.timestamp.isoformat() if m.timestamp else "",
                sender=m.sender,
                sender_name=m.sender_name,
                session_id=m.session_id,
                text=m.text,
                agent_id=m.agent_id,
                deployment_id=m.deployment_id,
                category=m.category or "message",
                properties=m.properties if isinstance(m.properties, dict) else None,
                content_blocks=m.content_blocks if m.content_blocks else None,
            )
            for m in messages
            # Safety net: skip messages with empty text that were persisted by
            # intermediate graph nodes before the orch_skip_node_persist fix.
            if (m.text and m.text.strip()) or m.category == "context_reset"
        ]
    except Exception as e:
        logger.error(f"Error getting orch session messages: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e



@router.delete("/sessions/{session_id}", status_code=204)
async def delete_orch_session(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    session_id: str,
):
    """Delete all messages and transactions for an orchestrator session."""
    try:
        await orch_delete_session(session, session_id, user_id=current_user.id)
        await orch_delete_session_transactions(session, session_id)
    except Exception as e:
        logger.error(f"Error deleting orch session: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════
# 6. Rename a session
# ═══════════════════════════════════════════════════════════════════════════


@router.patch("/sessions/{session_id}", status_code=200)
async def rename_orch_session(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    session_id: str,
    new_session_id: str = Query(..., description="New session identifier"),
):
    """Rename an orchestrator session (updates session_id on all messages)."""
    try:
        count = await orch_rename_session(session, session_id, new_session_id, user_id=current_user.id)
        return {"updated": count, "new_session_id": new_session_id}
    except Exception as e:
        logger.error(f"Error renaming orch session: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e




class ActiveAgentResponse(BaseModel):
    agent_id: UUID | None = None
    deployment_id: UUID | None = None
    agent_name: str | None = None


@router.get(
    "/sessions/{session_id}/active-agent",
    response_model=ActiveAgentResponse,
    status_code=200,
)
async def get_active_agent(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
    session_id: str,
):
    """Return the currently active (sticky) agent for a session.

    Returns null fields if the session has no messages yet.
    """
    try:
        active = await orch_get_active_agent(session, session_id)
        if not active:
            return ActiveAgentResponse()
        dep = await session.get(AgentDeploymentProd, active["deployment_id"])
        if not dep:
            dep = await session.get(AgentDeploymentUAT, active["deployment_id"])
        return ActiveAgentResponse(
            agent_id=active["agent_id"],
            deployment_id=active["deployment_id"],
            agent_name=dep.agent_name if dep else None,
        )
    except Exception as e:
        logger.error(f"Error getting active agent: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
