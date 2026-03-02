import { BuildStatus } from "@/constants/enums";
import useAgentStore from "@/stores/agentStore";
import type { NodeDataType } from "@/types/agent";

export const useBuildStatus = (data: NodeDataType, nodeId: string) => {
  return useAgentStore((state) => {
    // Early return if no agent data
    if (!data.node?.agent?.data?.nodes) {
      return state.agentBuildStatus[nodeId]?.status;
    }

    const nodes = data.node.agent.data.nodes;
    const buildStatuses = nodes
      .map((node) => state.agentBuildStatus[node.id]?.status)
      .filter(Boolean);

    // If no build statuses found, return the single node status
    if (buildStatuses.length === 0) {
      return state.agentBuildStatus[nodeId]?.status;
    }

    // Check statuses in order of priority
    if (buildStatuses.every((status) => status === BuildStatus.BUILT)) {
      return BuildStatus.BUILT;
    }
    if (buildStatuses.some((status) => status === BuildStatus.BUILDING)) {
      return BuildStatus.BUILDING;
    }
    if (buildStatuses.some((status) => status === BuildStatus.ERROR)) {
      return BuildStatus.ERROR;
    }

    return BuildStatus.TO_BUILD;
  });
};
