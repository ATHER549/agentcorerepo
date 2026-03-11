import type {
  Connection,
  Node,
  OnEdgesChange,
  OnNodesChange,
  reactFlowInstance,
  Viewport,
} from "@xyflow/react";
import type { AllNodeType, EdgeType, AgentType } from "@/types/agent";
import type { BuildStatus, EventDeliveryType } from "../../../constants/enums";
import type { VertexBuildTypeAPI } from "../../api";
import type { ChatInputType, ChatOutputType } from "../../chat";
import type { AgentState } from "../../tabs";

export type AgentPoolObjectType = {
  timestamp: string;
  valid: boolean;
  messages: Array<ChatOutputType | ChatInputType> | [];
  data: {
    artifacts: any | ChatOutputType | ChatInputType;
    results: any | ChatOutputType | ChatInputType;
  };
  duration?: string;
  progress?: number;
  id: string;
  buildId: string;
};

export type AgentPoolObjectTypeNew = {
  //build
  //1 - error->logs
  //2 - success-> result
  timestamp: string;
  valid: boolean;
  data: {
    outputs?: any | ChatOutputType | ChatInputType;
    results: any | ChatOutputType | ChatInputType;
  };
  duration?: string;
  progress?: number;
  //retrieve component type from id
  id: string;
  buildId: string;
};

export type VertexLayerElementType = {
  id: string;
  reference?: string;
};

export type AgentPoolType = {
  [key: string]: Array<VertexBuildTypeAPI>;
};

export type ComponentsToUpdateType = {
  id: string;
  icon?: string;
  display_name: string;
  outdated: boolean;
  breakingChange: boolean;
  userEdited: boolean;
};

export type AgentStoreType = {
  dismissedNodes: string[];
  addDismissedNodes: (dismissedNodes: string[]) => void;
  removeDismissedNodes: (dismissedNodes: string[]) => void;
  dismissedNodesLegacy: string[];
  addDismissedNodesLegacy: (dismissedNodes: string[]) => void;
  //key x, y
  positionDictionary: { [key: number]: number };
  isPositionAvailable: (position: { x: number; y: number }) => boolean;
  setPositionDictionary: (positionDictionary: {
    [key: number]: number;
  }) => void;
  fitViewNode: (nodeId: string) => void;
  autoSaveAgent: (() => void) | undefined;
  componentsToUpdate: ComponentsToUpdateType[];
  setComponentsToUpdate: (
    update:
      | ComponentsToUpdateType[]
      | ((oldState: ComponentsToUpdateType[]) => ComponentsToUpdateType[]),
  ) => void;
  updateComponentsToUpdate: (nodes: AllNodeType[]) => void;
  onAgentBuilderPage: boolean;
  setOnAgentBuilderPage: (onAgentBuilderPage: boolean) => void;
  agentPool: AgentPoolType;
  setHasIO: (hasIO: boolean) => void;
  setInputs: (
    inputs: Array<{ type: string; id: string; displayName: string }>,
  ) => void;
  setOutputs: (
    outputs: Array<{ type: string; id: string; displayName: string }>,
  ) => void;
  inputs: Array<{
    type: string;
    id: string;
    displayName: string;
  }>;
  outputs: Array<{
    type: string;
    id: string;
    displayName: string;
  }>;
  hasIO: boolean;
  setAgentPool: (agentPool: AgentPoolType) => void;
  addDataToAgentPool: (data: VertexBuildTypeAPI, nodeId: string) => void;
  CleanAgentPool: () => void;
  isBuilding: boolean;
  isPending: boolean;
  setIsBuilding: (isBuilding: boolean) => void;
  setPending: (isPending: boolean) => void;
  resetAgent: (agent: AgentType | undefined) => void;
  resetAgentState: () => void;
  reactFlowInstance: reactFlowInstance<AllNodeType, EdgeType> | null;
  setreactFlowInstance: (
    newState: reactFlowInstance<AllNodeType, EdgeType>,
  ) => void;
  agentState: AgentState | undefined;
  setAgentState: (
    state:
      | AgentState
      | undefined
      | ((oldState: AgentState | undefined) => AgentState),
  ) => void;
  nodes: AllNodeType[];
  edges: EdgeType[];
  onNodesChange: OnNodesChange<AllNodeType>;
  onEdgesChange: OnEdgesChange<EdgeType>;
  setNodes: (
    update: AllNodeType[] | ((oldState: AllNodeType[]) => AllNodeType[]),
  ) => void;
  setEdges: (
    update: EdgeType[] | ((oldState: EdgeType[]) => EdgeType[]),
  ) => void;
  setNode: (
    id: string,
    update: AllNodeType | ((oldState: AllNodeType) => AllNodeType),
    isUserChange?: boolean,
    callback?: () => void,
  ) => void;
  getNode: (id: string) => AllNodeType | undefined;
  deleteNode: (nodeId: string | Array<string>) => void;
  deleteEdge: (edgeId: string | Array<string>) => void;
  paste: (
    selection: { nodes: any; edges: any },
    position: { x: number; y: number; paneX?: number; paneY?: number },
  ) => void;
  lastCopiedSelection: { nodes: any; edges: any } | null;
  setLastCopiedSelection: (
    newSelection: { nodes: any; edges: any } | null,
    isCrop?: boolean,
  ) => void;
  cleanAgent: () => void;
  setFilterEdge: (newState) => void;
  getFilterEdge: any[];
  setFilterComponent: (newState) => void;
  getFilterComponent: string;
  onConnect: (connection: Connection) => void;
  unselectAll: () => void;
  playgroundPage: boolean;
  setPlaygroundPage: (playgroundPage: boolean) => void;
  buildInfo: { error?: string[]; success?: boolean } | null;
  setBuildInfo: (
    buildInfo: { error?: string[]; success?: boolean } | null,
  ) => void;
  pastBuildAgentParams: {
    startNodeId?: string;
    stopNodeId?: string;
    input_value?: string;
    files?: string[];
    silent?: boolean;
    session?: string;
    stream?: boolean;
    eventDelivery?: EventDeliveryType;
  } | null;
  buildAgent: ({
    startNodeId,
    stopNodeId,
    input_value,
    files,
    silent,
    session,
    stream,
    eventDelivery,
  }: {
    startNodeId?: string;
    stopNodeId?: string;
    input_value?: string;
    files?: string[];
    silent?: boolean;
    session?: string;
    stream?: boolean;
    eventDelivery?: EventDeliveryType;
  }) => Promise<void>;
  getAgent: () => { nodes: Node[]; edges: EdgeType[]; viewport: Viewport };
  updateVerticesBuild: (
    vertices: {
      verticesIds: string[];
      verticesLayers: VertexLayerElementType[][];
      runId?: string;
      verticesToRun: string[];
    } | null,
  ) => void;
  addToVerticesBuild: (vertices: string[]) => void;
  removeFromVerticesBuild: (vertices: string[]) => void;
  verticesBuild: {
    verticesIds: string[];
    verticesLayers: VertexLayerElementType[][];
    runId?: string;
    verticesToRun: string[];
  } | null;
  updateBuildStatus: (nodeIdList: string[], status: BuildStatus) => void;
  revertBuiltStatusFromBuilding: () => void;
  agentBuildStatus: {
    [key: string]: {
      status: BuildStatus;
      timestamp?: string;
    };
  };
  updateAgentPool: (
    nodeId: string,
    data: VertexBuildTypeAPI | ChatOutputType | ChatInputType,
    buildId?: string,
  ) => void;
  getNodePosition: (nodeId: string) => { x: number; y: number };
  updateFreezeStatus: (nodeIds: string[], freeze: boolean) => void;
  currentAgent: AgentType | undefined;
  setCurrentAgent: (agent: AgentType | undefined) => void;
  updateCurrentAgent: ({
    nodes,
    edges,
    viewport,
  }: {
    nodes?: AllNodeType[];
    edges?: EdgeType[];
    viewport?: Viewport;
  }) => void;
  handleDragging:
    | {
        source: string | undefined;
        sourceHandle: string | undefined;
        target: string | undefined;
        targetHandle: string | undefined;
        type: string;
        color: string;
      }
    | undefined;
  setHandleDragging: (
    data:
      | {
          source: string | undefined;
          sourceHandle: string | undefined;
          target: string | undefined;
          targetHandle: string | undefined;
          type: string;
          color: string;
        }
      | undefined,
  ) => void;

  filterType:
    | {
        source: string | undefined;
        sourceHandle: string | undefined;
        target: string | undefined;
        targetHandle: string | undefined;
        type: string;
        color: string;
      }
    | undefined;
  setFilterType: (
    data:
      | {
          source: string | undefined;
          sourceHandle: string | undefined;
          target: string | undefined;
          targetHandle: string | undefined;
          type: string;
          color: string;
        }
      | undefined,
  ) => void;
  updateEdgesRunningByNodes: (ids: string[], running: boolean) => void;
  stopBuilding: () => void;
  buildController: AbortController;
  setBuildController: (controller: AbortController) => void;
  currentBuildingNodeId: string[] | undefined;
  setCurrentBuildingNodeId: (nodeIds: string[] | undefined) => void;
  clearEdgesRunningByNodes: () => Promise<void>;
  updateToolMode: (nodeId: string, toolMode: boolean) => void;
  helperLineEnabled: boolean;
  setHelperLineEnabled: (helperLineEnabled: boolean) => void;
  newChatOnPlayground: boolean;
  setNewChatOnPlayground: (newChat: boolean) => void;
};
