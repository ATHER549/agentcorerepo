import { cloneDeep } from "lodash";
import { create } from "zustand";
import { SAVE_DEBOUNCE_TIME } from "@/constants/constants";
import type { AgentType } from "../types/agent";
import type {
  AgentsManagerStoreType,
  UseUndoRedoOptions,
} from "../types/zustand/agentsManager";
import useAgentStore from "./agentStore";

const defaultOptions: UseUndoRedoOptions = {
  maxHistorySize: 100,
  enableShortcuts: true,
};

const past = {};
const future = {};

const useAgentsManagerStore = create<AgentsManagerStoreType>((set, get) => ({
  IOModalOpen: false,
  setIOModalOpen: (IOModalOpen: boolean) => {
    set({ IOModalOpen });
  },
  healthCheckMaxRetries: 5,
  setHealthCheckMaxRetries: (healthCheckMaxRetries: number) =>
    set({ healthCheckMaxRetries }),
  autoSaving: true,
  setAutoSaving: (autoSaving: boolean) => set({ autoSaving }),
  autoSavingInterval: SAVE_DEBOUNCE_TIME,
  setAutoSavingInterval: (autoSavingInterval: number) =>
    set({ autoSavingInterval }),
  examples: [],
  setExamples: (examples: AgentType[]) => {
    set({ examples });
  },
  currentAgentId: "",
  setCurrentAgent: (agent: AgentType | undefined) => {
    set({
      currentAgent: agent,
      currentAgentId: agent?.id ?? "",
    });
    useAgentStore.getState().resetAgent(agent);
  },
  getAgentById: (id: string) => {
    return get().agents?.find((agent) => agent.id === id);
  },
  agents: undefined,
  setAgents: (agents: AgentType[]) => {
    set({
      agents,
      currentAgent: agents.find((agent) => agent.id === get().currentAgentId),
    });
  },
  currentAgent: undefined,
  saveLoading: false,
  setSaveLoading: (saveLoading: boolean) => set({ saveLoading }),
  isLoading: false,
  setIsLoading: (isLoading: boolean) => set({ isLoading }),
  takeSnapshot: () => {
    const currentAgentId = get().currentAgentId;
    // push the current graph to the past state
    const agentStore = useAgentStore.getState();
    const newState = {
      nodes: cloneDeep(agentStore.nodes),
      edges: cloneDeep(agentStore.edges),
    };
    const pastLength = past[currentAgentId]?.length ?? 0;
    if (
      pastLength > 0 &&
      JSON.stringify(past[currentAgentId][pastLength - 1]) ===
        JSON.stringify(newState)
    )
      return;
    if (pastLength > 0) {
      past[currentAgentId] = past[currentAgentId].slice(
        pastLength - defaultOptions.maxHistorySize + 1,
        pastLength,
      );

      past[currentAgentId].push(newState);
    } else {
      past[currentAgentId] = [newState];
    }

    future[currentAgentId] = [];
  },
  undo: () => {
    const newState = useAgentStore.getState();
    const currentAgentId = get().currentAgentId;
    const pastLength = past[currentAgentId]?.length ?? 0;
    const pastState = past[currentAgentId]?.[pastLength - 1] ?? null;

    if (pastState) {
      past[currentAgentId] = past[currentAgentId].slice(0, pastLength - 1);

      if (!future[currentAgentId]) future[currentAgentId] = [];
      future[currentAgentId].push({
        nodes: newState.nodes,
        edges: newState.edges,
      });

      newState.setNodes(pastState.nodes);
      newState.setEdges(pastState.edges);
    }
  },
  redo: () => {
    const newState = useAgentStore.getState();
    const currentAgentId = get().currentAgentId;
    const futureLength = future[currentAgentId]?.length ?? 0;
    const futureState = future[currentAgentId]?.[futureLength - 1] ?? null;

    if (futureState) {
      future[currentAgentId] = future[currentAgentId].slice(0, futureLength - 1);

      if (!past[currentAgentId]) past[currentAgentId] = [];
      past[currentAgentId].push({
        nodes: newState.nodes,
        edges: newState.edges,
      });

      newState.setNodes(futureState.nodes);
      newState.setEdges(futureState.edges);
    }
  },
  searchAgentsComponents: "",
  setSearchAgentsComponents: (searchAgentsComponents: string) => {
    set({ searchAgentsComponents });
  },
  selectedAgentsComponentsCards: [],
  setSelectedAgentsComponentsCards: (selectedAgentsComponentsCards: string[]) => {
    set({ selectedAgentsComponentsCards });
  },
  resetStore: () => {
    set({
      agents: [],
      currentAgent: undefined,
      currentAgentId: "",
      searchAgentsComponents: "",
      selectedAgentsComponentsCards: [],
    });
  },
}));

export default useAgentsManagerStore;
