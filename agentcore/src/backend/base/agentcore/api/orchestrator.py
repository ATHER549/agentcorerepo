
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
from sqlmodel import col, select

from fastapi.responses import StreamingResponse

from agentcore.api.utils import CurrentActiveUser, DbSession, build_graph_from_data
from agentcore.api.v1_schemas import InputValueRequest, RunResponse
from agentcore.events.event_manager import EventManager, create_default_event_manager
from agentcore.services.database.models.agent_deployment_prod.model import (
    AgentDeploymentProd,
    DeploymentPRODStatusEnum,
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
):
    """Build a graph from a published snapshot, ready for execution.

    Returns (graph, inputs, outputs).
    """
    from agentcore.processing.process import process_tweaks

    graph_data = snapshot.copy()
    graph_data = process_tweaks(graph_data, {}, stream=stream)

    graph = await build_graph_from_data(
        agent_id=agent_id,
        payload=graph_data,
        user_id=user_id,
        agent_name=agent_name,
    )

    if stream:
        for vertex in graph.vertices:
            if isinstance(vertex.template.get("stream"), dict):
                vertex.update_raw_params({"stream": True}, overwrite=True)

    # Orchestration chat persists messages/transactions in its own tables.
    graph.skip_dev_logging = True

    # Pass orch context so the adapter logs to orch_transaction.
    graph.orch_session_id = session_id
    graph.orch_deployment_id = deployment_id
    graph.orch_org_id = org_id
    graph.orch_dept_id = dept_id

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
) -> tuple[str, str | None]:
    """Build a graph from a published snapshot and run it.

    Returns (response_text, session_id).
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


    run_response = RunResponse(outputs=task_result, session_id=result_session_id)
    encoded = jsonable_encoder(run_response)
    logger.debug(f"[ORCH] RunResponse encoded payload: {json.dumps(encoded, default=str)[:2000]}")
    response_text = _extract_text(encoded)
    logger.info(f"[ORCH] Extracted response text: {response_text[:500] if response_text else '(empty)'}")

    return response_text, result_session_id



async def _resolve_agent(
    session,
    body: OrchChatRequest,
) -> tuple[UUID, UUID, AgentDeploymentProd]:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment {deployment_id} not found",
        )

    return agent_id, deployment_id, deployment


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
    """Return all PROD-deployed agents that are PUBLISHED, active, and enabled."""
    try:
        stmt = (
            select(AgentDeploymentProd)
            .where(AgentDeploymentProd.status == DeploymentPRODStatusEnum.PUBLISHED)
            .where(AgentDeploymentProd.is_active == True)  # noqa: E712
            .where(AgentDeploymentProd.is_enabled == True)  # noqa: E712
            .order_by(col(AgentDeploymentProd.agent_name).asc())
        )
        records = (await session.exec(stmt)).all()
        return [
            OrchAgentSummary(
                deploy_id=r.id,
                agent_id=r.agent_id,
                agent_name=r.agent_name,
                agent_description=r.agent_description,
                version_number=r.version_number,
            )
            for r in records
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
        agent_id, deployment_id, deployment = await _resolve_agent(session, body)

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

        # -- 4. Run the agent from its frozen PROD snapshot ----------------
        logger.info(f"[ORCH] Agent={deployment.agent_name} | session={body.session_id} | input_value={body.input_value!r}")
        agent_text, _ = await _run_agent_from_snapshot(
            agent_id=str(agent_id),
            agent_name=deployment.agent_name,
            snapshot=deployment.agent_snapshot,
            input_value=body.input_value,
            session_id=body.session_id,
            user_id=str(current_user.id),
            deployment_id=str(deployment_id),
            org_id=str(deployment.org_id) if deployment.org_id else None,
            dept_id=str(deployment.dept_id) if deployment.dept_id else None,
        )

        if not agent_text or not agent_text.strip():
            agent_text = "Agent did not produce a response."

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
            content_blocks=[],
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
    agent_id, deployment_id, deployment = await _resolve_agent(session, body)

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

    async def _run_and_persist():
        """Background coroutine: run the agent, persist reply, close the queue."""
        try:
            agent_text, _ = await _run_agent_from_snapshot(
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
            )
            if not agent_text or not agent_text.strip():
                agent_text = "Agent did not produce a response."

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
                    content_blocks=[],
                )
                await orch_add_message(agent_msg, db)

            # Signal end with final data so the frontend can finalize
            event_manager.on_end(data={
                "agent_text": agent_text,
                "message_id": str(agent_msg.id),
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
            )
            for m in messages
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
        await orch_delete_session(session, session_id)
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
        count = await orch_rename_session(session, session_id, new_session_id)
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
        return ActiveAgentResponse(
            agent_id=active["agent_id"],
            deployment_id=active["deployment_id"],
            agent_name=dep.agent_name if dep else None,
        )
    except Exception as e:
        logger.error(f"Error getting active agent: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
