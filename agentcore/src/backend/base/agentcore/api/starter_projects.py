from fastapi import APIRouter, HTTPException

from agentcore.graph_langgraph import GraphDump
from agentcore.initial_setup.load import get_starter_projects_dump

router = APIRouter(prefix="/starter-projects", tags=["agents"])


@router.get("/", status_code=200)
async def get_starter_projects() -> list[GraphDump]:
    """Get a list of starter projects."""

    try:
        return get_starter_projects_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
