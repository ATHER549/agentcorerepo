from agentcore.api.api_key import router as api_key_router
from agentcore.api.chat import router as chat_router
from agentcore.api.endpoints import router as endpoints_router
from agentcore.api.files_agent import router as files_router
from agentcore.api.agent import router as agents_router
from agentcore.api.health_check_router import health_check_router
from agentcore.api.log_router import log_router
from agentcore.api.login import router as login_router
from agentcore.api.monitor import router as monitor_router
from agentcore.api.observability import router as observability_router
from agentcore.api.evaluation import router as evaluation_router
from agentcore.api.projects import router as projects_router
from agentcore.api.publish import router as publish_router
from agentcore.api.approvals import router as approvals_router
from agentcore.api.router import router
from agentcore.api.roles import router as roles_router
from agentcore.api.organizations import router as organizations_router
from agentcore.api.departments import router as departments_router
from agentcore.api.starter_projects import router as starter_projects_router
from agentcore.api.users import router as users_router
from agentcore.api.validate import router as validate_router
from agentcore.api.variable import router as variables_router
from agentcore.api.files_user import router as files_router_v2
from agentcore.api.mcp_config import router as mcp_router_v2
from agentcore.api.help_support import router as help_support_router
from agentcore.api.a2a import router as a2a_router
from agentcore.api.packages import router as packages_router
from agentcore.api.teams import router as teams_router
from agentcore.api.triggers import router as triggers_router

__all__ = [
    "api_key_router",
    "chat_router",
    "endpoints_router",
    "files_router",
    "files_router_v2",
    "agents_router",
    "health_check_router",
    "log_router",
    "login_router",
    "mcp_router_v2",
    "monitor_router",
    "observability_router",
    "evaluation_router",
    "projects_router",
    "roles_router",
    "organizations_router",
    "departments_router",
    "approvals_router",
    "publish_router",
    "router",
    "starter_projects_router",
    "users_router",
    "validate_router",
    "variables_router",
    "help_support_router",
    "a2a_router",
    "packages_router",
    "teams_router",
    "triggers_router",
]
