from uuid import UUID

from fastapi import APIRouter, HTTPException

from agentcore.api.utils import CurrentActiveUser, DbSession

router = APIRouter(prefix="/variables", tags=["Variables"])

@router.post("/", status_code=201)
async def create_variable(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Azure Key Vault."""
    raise HTTPException(status_code=501, detail="Azure Key Vault")


@router.get("/", status_code=200)
async def read_variables(
    *,
    session: DbSession,
    current_user: CurrentActiveUser,
):
    """Read all variables"""
    return []


@router.patch("/{variable_id}", status_code=200)
async def update_variable(
    *,
    session: DbSession,
    variable_id: UUID,
    current_user: CurrentActiveUser,
):
    """Azure Key Vault."""
    raise HTTPException(status_code=501, detail="Azure Key Vault")


@router.delete("/{variable_id}", status_code=204)
async def delete_variable(
    *,
    session: DbSession,
    variable_id: UUID,
    current_user: CurrentActiveUser,
) -> None:
    """ Azure Key Vault."""
    raise HTTPException(status_code=501, detail=" Azure Key Vault")
