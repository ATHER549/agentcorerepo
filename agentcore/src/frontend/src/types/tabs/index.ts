import type { XYPosition } from "@xyflow/react";
import type { AgentType, NodeDataType } from "../agent";

export type AgentsContextType = {
  //keep
  saveAgent: (agent?: AgentType, silent?: boolean) => Promise<void>;
  tabId: string;
  //keep
  isLoading: boolean;
  setTabId: (index: string) => void;
  //keep
  removeAgent: (id: string) => void;
  refreshAgents: () => void;
  //keep
  addAgent: (
    newProject: boolean,
    agent?: AgentType,
    override?: boolean,
    position?: XYPosition,
  ) => Promise<string | undefined>;
  downloadAgent: (
    agent: AgentType,
    agentName: string,
    agentDescription?: string,
  ) => void;
  //keep
  downloadAgents: () => void;
  //keep
  uploadAgents: () => void;
  setVersion: (version: string) => void;
  uploadAgent: ({
    newProject,
    file,
    isComponent,
    position,
  }: {
    newProject: boolean;
    file?: File;
    isComponent?: boolean;
    position?: XYPosition;
  }) => Promise<string | never>;
  tabsState: AgentsState;
  setTabsState: (
    update: AgentsState | ((oldState: AgentsState) => AgentsState),
  ) => void;
  saveComponent: (
    component: NodeDataType,
    override: boolean,
  ) => Promise<string | undefined>;
  deleteComponent: (key: string) => void;
  version: string;
  agents: Array<AgentType>;
};

export type AgentsState = {
  [key: string]: AgentState | undefined;
};

export type AgentState = {
  template?: string;
  input_keys?: Object;
  memory_keys?: Array<string>;
  handle_keys?: Array<string>;
};

export type errorsVarType = {
  title: string;
  list?: Array<string>;
};

export type APITabType = {
  title: string;
  language: string;
  icon: string;
  code: string;
  copyCode: string;
};

export type tabsArrayType = Array<APITabType>;
