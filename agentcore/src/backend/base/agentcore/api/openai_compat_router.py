from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Security
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import select

from agentcore.api.endpoints import simple_run_agent
from agentcore.api.v1_schemas import SimplifiedAPIRequest
from agentcore.helpers.agent import get_agent_by_id_or_endpoint_name
from agentcore.services.auth.utils import api_key_header, api_key_query, api_key_security
from agentcore.services.database.models.agent.model import AccessTypeEnum, Agent, AgentRead
from agentcore.services.deps import session_scope

if TYPE_CHECKING:
    from agentcore.services.database.models.user.model import UserRead
else:  # pragma: no cover - runtime fallback for forward annotations
    UserRead = Any  # type: ignore[assignment]

router = APIRouter(tags=["OpenAI-Compatible"])


# --- minimal OpenAI request/response types ---
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float | None = 0.2
    stream: bool | None = False
    max_tokens: int | None = None


def _extract_text(payload: Any) -> str:
    """Extract a human-readable response from AgentCore run payloads."""
    if isinstance(payload, str):
        return payload

    def ensure_text(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value
        return None

    def best_from_message(msg: Any) -> str | None:
        if isinstance(msg, dict):
            # order matters: message -> text -> data.text
            candidates = [
                msg.get("message"),
                msg.get("text"),
                msg.get("data", {}).get("text") if isinstance(msg.get("data"), dict) else None,
            ]
            for candidate in candidates:
                text = ensure_text(candidate)
                if text:
                    return text
        elif isinstance(msg, list):
            for item in msg:
                text = best_from_message(item)
                if text:
                    return text
        return ensure_text(msg)

    if isinstance(payload, dict):
        outputs = payload.get("outputs") or []
        for run_output in outputs:
            if not isinstance(run_output, dict):
                continue
            # check nested result entries
            for result_entry in run_output.get("outputs") or []:
                if not isinstance(result_entry, dict):
                    continue
                text = (
                    best_from_message(result_entry.get("results"))
                    or best_from_message(result_entry.get("outputs"))
                    or best_from_message(result_entry.get("messages"))
                )
                if text:
                    return text
        # fallback to recursive search
        for value in payload.values():
            text = best_from_message(value)
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


def _last_user(msgs: list[ChatMessage]) -> str:
    for m in reversed(msgs):
        if m.role == "user":
            return m.content
    return "\n\n".join(m.content for m in msgs)


async def _resolve_current_user(
    authorization: str | None = Header(default=None),
    query_key: Annotated[str | None, Security(api_key_query)] = None,
    header_key: Annotated[str | None, Security(api_key_header)] = None,
) -> UserRead:
    """Resolve the AgentCore user based on OpenAI-style headers.

    OpenAI clients typically send API keys via the Authorization header (Bearer ...)
    while AgentCore also supports the x-api-key header/query parameter. We accept
    either format and delegate to the shared api_key_security helper.
    """
    bearer_key: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_key = authorization.split(" ", 1)[1].strip()
    token = bearer_key or header_key or query_key
    return await api_key_security(query_key or token, header_key or token)


async def _fetch_accessible_agents(user: UserRead) -> list[Agent]:
    """Return agents that the caller can access via the OpenAI shim."""
    async with session_scope() as session:
        stmt = (
            select(Agent)
            .where(
                or_(
                    Agent.user_id == user.id,
                    Agent.access_type == AccessTypeEnum.PUBLIC,
                )
            )
        )
        return list((await session.exec(stmt)).all())


def _model_identifier(agent: Agent, *, include_prefix: bool = True) -> str:
    suffix = str(agent.id)
    return f"lb:{suffix}" if include_prefix else suffix


def _agent_to_model_payload(agent: Agent) -> dict[str, Any]:
    updated = agent.updated_at
    if isinstance(updated, str):
        try:
            updated_dt = datetime.fromisoformat(updated)
        except ValueError:
            updated_dt = None
    else:
        updated_dt = updated
    created_ts = int(updated_dt.timestamp()) if updated_dt else int(time.time())
    return {
        "id": _model_identifier(agent),
        "name": agent.name,
        "object": "model",
        "created": created_ts,
        "owned_by": str(agent.user_id) if agent.user_id else None,
        "root": _model_identifier(agent),
        "parent": None,
        "permission": [],
        "metadata": {
            "display_name": agent.name,
            "description": agent.description,
            "agent_id": str(agent.id),
            "access": agent.access_type.value if agent.access_type else AccessTypeEnum.PRIVATE.value,
        },
    }


def _build_agent_lookup(agents: list[Agent]) -> dict[str, AgentRead]:
    lookup: dict[str, AgentRead] = {}
    for agent in agents:
        agent_read = AgentRead.model_validate(agent, from_attributes=True)
        for key in {
            str(agent.id),
            _model_identifier(agent),
            _model_identifier(agent, include_prefix=False),
            f"lb:{agent.id}",
        }:
            lookup[key] = agent_read
    return lookup


def _ensure_agent_access(agent: AgentRead, user: UserRead) -> None:
    if agent.access_type == AccessTypeEnum.PUBLIC:
        return
    if agent.user_id and agent.user_id == user.id:
        return
    raise HTTPException(status_code=403, detail="Agent is not accessible with this API key")


@router.get("/v1/models")
async def list_models(current_user: Annotated[UserRead, Depends(_resolve_current_user)]):
    agents = await _fetch_accessible_agents(current_user)
    if not agents:
        return {"object": "list", "data": []}
    return {"object": "list", "data": [_agent_to_model_payload(agent) for agent in agents]}


@router.post("/v1/chat/completions")
async def chat(req: ChatRequest, current_user: Annotated[UserRead, Depends(_resolve_current_user)]):
    if req.stream:
        req.stream = False  # type: ignore[assignment]
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    agents = await _fetch_accessible_agents(current_user)
    if not agents:
        raise HTTPException(status_code=404, detail="No agents available for this account")

    agent_lookup = _build_agent_lookup(agents)
    requested_model = req.model or _model_identifier(agents[0])
    agent_key = requested_model.split(":", 1)[1] if requested_model.startswith("lb:") else requested_model
    agent_read = agent_lookup.get(requested_model) or agent_lookup.get(agent_key)
    if agent_read is None:
        # attempt to resolve via helper that checks DB + permissions
        target_identifier = agent_key
        agent_read = await get_agent_by_id_or_endpoint_name(target_identifier, user_id=str(current_user.id))
        _ensure_agent_access(agent_read, current_user)
    else:
        _ensure_agent_access(agent_read, current_user)

    prompt = _last_user(req.messages)
    simplified_request = SimplifiedAPIRequest(
        input_value=prompt,
        input_type="chat",
        output_type="chat",
    )
    run_response = await simple_run_agent(agent=agent_read, input_request=simplified_request, api_key_user=current_user)
    lb_json = run_response.model_dump()
    text = _extract_text(lb_json)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
