import type { AgentType } from "../../agent";

export type AgentsManagerStoreType = {
  autoSaving: boolean;
  setAutoSaving: (autoSaving: boolean) => void;
  getAgentById: (id: string) => AgentType | undefined;
  agents: Array<AgentType> | undefined;
  setAgents: (agents: AgentType[]) => void;
  currentAgent: AgentType | undefined;
  currentAgentId: string;
  saveLoading: boolean;
  setSaveLoading: (saveLoading: boolean) => void;
  isLoading: boolean;
  setIsLoading: (isLoading: boolean) => void;
  undo: () => void;
  redo: () => void;
  takeSnapshot: () => void;
  examples: Array<AgentType>;
  setExamples: (examples: AgentType[]) => void;
  setCurrentAgent: (agent?: AgentType) => void;
  setSearchAgentsComponents: (search: string) => void;
  searchAgentsComponents: string;
  selectedAgentsComponentsCards: string[];
  setSelectedAgentsComponentsCards: (selected: string[]) => void;
  autoSavingInterval: number;
  setAutoSavingInterval: (autoSavingInterval: number) => void;
  healthCheckMaxRetries: number;
  setHealthCheckMaxRetries: (healthCheckMaxRetries: number) => void;
  IOModalOpen: boolean;
  setIOModalOpen: (IOModalOpen: boolean) => void;
  resetStore: () => void;
};

export type UseUndoRedoOptions = {
  maxHistorySize: number;
  enableShortcuts: boolean;
};
