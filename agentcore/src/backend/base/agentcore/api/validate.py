from uuid import UUID

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from agentcore.api.utils import CurrentActiveUser
from agentcore.api.utils import DbSession
from agentcore.api.base import Code, CodeValidationResponse, PromptValidationResponse, ValidatePromptRequest
from agentcore.base.prompts.api_utils import process_prompt_template
from agentcore.services.database.models.agent.model import Agent
from agentcore.services.database.models.connector_catalogue.model import ConnectorCatalogue
from agentcore.services.database.models.guardrail_catalogue.model import GuardrailCatalogue
from agentcore.services.database.models.mcp_registry.model import McpRegistry
from agentcore.utils.validate import validate_code

# build router
router = APIRouter(prefix="/validate", tags=["Validate"])


@router.post("/code", status_code=200)
async def post_validate_code(code: Code, _current_user: CurrentActiveUser) -> CodeValidationResponse:
    try:
        errors = validate_code(code.code)
        return CodeValidationResponse(
            imports=errors.get("imports", {}),
            function=errors.get("function", {}),
        )
    except Exception as e:
        logger.opt(exception=True).debug("Error validating code")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/prompt", status_code=200)
async def post_validate_prompt(prompt_request: ValidatePromptRequest) -> PromptValidationResponse:
    try:
        if not prompt_request.frontend_node:
            return PromptValidationResponse(
                input_variables=[],
                frontend_node=None,
            )

        # Process the prompt template using direct attributes
        input_variables = process_prompt_template(
            template=prompt_request.template,
            name=prompt_request.name,
            custom_fields=prompt_request.frontend_node.custom_fields,
            frontend_node_template=prompt_request.frontend_node.template,
        )

        return PromptValidationResponse(
            input_variables=input_variables,
            frontend_node=prompt_request.frontend_node,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class NameValidationRequest(BaseModel):
    entity: str  # agent | mcp | connector | guardrail
    name: str
    org_id: UUID | None = None
    dept_id: UUID | None = None
    exclude_id: UUID | None = None


class NameValidationResponse(BaseModel):
    available: bool
    reason: str | None = None


def _equals_or_null(column, value):
    return column.is_(None) if value is None else column == value


@router.post("/name", response_model=NameValidationResponse, status_code=200)
async def post_validate_name(
    payload: NameValidationRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> NameValidationResponse:
    normalized_entity = payload.entity.strip().lower()
    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="name is required")

    lowered_name = normalized_name.lower()

    if normalized_entity == "agent":
        stmt = select(Agent.id).where(
            Agent.user_id == current_user.id,
            func.lower(Agent.name) == lowered_name,
        )
        if payload.exclude_id:
            stmt = stmt.where(Agent.id != payload.exclude_id)
        existing = (await session.exec(stmt)).first()
        return NameValidationResponse(
            available=existing is None,
            reason=None if existing is None else "This agent name is already taken.",
        )

    if normalized_entity == "mcp":
        stmt = select(McpRegistry.id).where(func.lower(McpRegistry.server_name) == lowered_name)
        if payload.exclude_id:
            stmt = stmt.where(McpRegistry.id != payload.exclude_id)
        existing = (await session.exec(stmt)).first()
        return NameValidationResponse(
            available=existing is None,
            reason=None if existing is None else "This MCP server name is already taken.",
        )

    if normalized_entity == "connector":
        stmt = select(ConnectorCatalogue.id).where(
            func.lower(ConnectorCatalogue.name) == lowered_name,
            _equals_or_null(ConnectorCatalogue.org_id, payload.org_id),
            _equals_or_null(ConnectorCatalogue.dept_id, payload.dept_id),
        )
        if payload.exclude_id:
            stmt = stmt.where(ConnectorCatalogue.id != payload.exclude_id)
        existing = (await session.exec(stmt)).first()
        return NameValidationResponse(
            available=existing is None,
            reason=None if existing is None else "This connector name is already taken for the selected scope.",
        )

    if normalized_entity == "guardrail":
        stmt = select(GuardrailCatalogue.id).where(
            func.lower(GuardrailCatalogue.name) == lowered_name,
            _equals_or_null(GuardrailCatalogue.org_id, payload.org_id),
            _equals_or_null(GuardrailCatalogue.dept_id, payload.dept_id),
        )
        if payload.exclude_id:
            stmt = stmt.where(GuardrailCatalogue.id != payload.exclude_id)
        existing = (await session.exec(stmt)).first()
        return NameValidationResponse(
            available=existing is None,
            reason=None if existing is None else "This guardrail name is already taken for the selected scope.",
        )

    raise HTTPException(status_code=400, detail=f"Unsupported entity '{payload.entity}'")
