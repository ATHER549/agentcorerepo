import type { Edge } from "@xyflow/react";
import type { AllNodeType, EdgeType, AgentType } from "../agent";

export type addEscapedHandleIdsToEdgesType = {
  edges: EdgeType[];
};

export type updateEdgesHandleIdsType = {
  nodes: AllNodeType[];
  edges: EdgeType[];
};

export type generateAgentType = { newAgent: AgentType; removedEdges: Edge[] };

export type findLastNodeType = {
  nodes: AllNodeType[];
  edges: EdgeType[];
};
