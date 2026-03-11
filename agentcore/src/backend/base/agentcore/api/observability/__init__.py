"""Observability API — modular package replacing the monolith.

Assembles endpoint routers under /observability with shared RBAC dependency.
Re-exports key functions used by other modules (e.g. evaluation.py).
"""

from fastapi import APIRouter, Depends

from agentcore.services.auth.decorators import PermissionChecker

from .endpoints.status import router as status_router
from .endpoints.traces import router as traces_router
from .endpoints.metrics import router as metrics_router
from .endpoints.sessions import router as sessions_router
from .endpoints.agents import router as agents_router
from .endpoints.projects import router as projects_router

# Backward-compat re-exports consumed by evaluation.py and others
from .trace_store import fetch_traces_from_langfuse  # noqa: F401
from .parsing import fetch_scores_for_trace  # noqa: F401
from .langfuse_client import (  # noqa: F401
    get_langfuse_client,
    get_langfuse_client_for_binding as _get_langfuse_client_for_binding,
)

router = APIRouter(
    prefix="/observability",
    tags=["Observability"],
    dependencies=[Depends(PermissionChecker(["view_observability_page"]))],
)

router.include_router(status_router)
router.include_router(traces_router)
router.include_router(metrics_router)
router.include_router(sessions_router)
router.include_router(agents_router)
router.include_router(projects_router)
