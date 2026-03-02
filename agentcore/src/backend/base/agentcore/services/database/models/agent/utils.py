from agentcore.utils.version import get_version_info

from .model import Agent


def get_webhook_component_in_agent(agent_data: dict):
    """Get webhook component in agent data."""
    if "nodes" in agent_data:
        for node in agent_data.get("nodes", []):
            if "Webhook" in node.get("id"):
                return node
    return None


def get_all_webhook_components_in_agent(agent_data: dict | None):
    """Get all webhook components in agent data."""
    if not agent_data:
        return []
    return [node for node in agent_data.get("nodes", []) if "Webhook" in node.get("id")]


def get_components_versions(agent: Agent):
    versions: dict[str, str] = {}
    if agent.data is None:
        return versions
    nodes = agent.data.get("nodes", [])
    for node in nodes:
        data = node.get("data", {})
        data_node = data.get("node", {})
        if "lf_version" in data_node:
            versions[node["id"]] = data_node["lf_version"]
    return versions


def get_outdated_components(agent: Agent):
    component_versions = get_components_versions(agent)
    lf_version = get_version_info()["version"]
    outdated_components = []
    for key, value in component_versions.items():
        if value != lf_version:
            outdated_components.append(key)
    return outdated_components
