import type { AllNodeType } from "@/types/agent";

export type TweaksStoreType = {
  nodes: AllNodeType[];
  currentAgentId: string;
  setNodes: (
    update: AllNodeType[] | ((oldState: AllNodeType[]) => AllNodeType[]),
    skipSave?: boolean,
  ) => void;
  setNode: (
    id: string,
    update: AllNodeType | ((oldState: AllNodeType) => AllNodeType),
  ) => void;
  getNode: (id: string) => AllNodeType | undefined;
  initialSetup: (nodes: AllNodeType[], agentId: string) => void;
  updateTweaks: () => void;
  tweaks: {
    [key: string]: {
      [key: string]: any;
    };
  };
};
