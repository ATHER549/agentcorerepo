import { create } from "zustand";
import { getChangesType } from "@/modals/apiModal/utils/get-changes-types";
import { getNodesWithDefaultValue } from "@/modals/apiModal/utils/get-nodes-with-default-value";
import type { AllNodeType, NodeDataType } from "@/types/agent";
import { getLocalStorage, setLocalStorage } from "@/utils/local-storage-util";
import type { TweaksStoreType } from "../types/zustand/tweaks";
import useAgentStore from "./agentStore";

export const useTweaksStore = create<TweaksStoreType>((set, get) => ({
  tweaks: {},
  nodes: [],
  setNodes: (change) => {
    const newChange =
      typeof change === "function" ? change(get().nodes) : change;

    set({
      nodes: newChange,
    });
    get().updateTweaks();
  },
  setNode: (id, change) => {
    const newChange =
      typeof change === "function"
        ? change(get().nodes.find((node) => node.id === id)!)
        : change;
    get().setNodes((oldNodes) =>
      oldNodes.map((node) => {
        if (node.id === id) {
          if ((node.data as NodeDataType).node?.frozen) {
            (newChange.data as NodeDataType).node!.frozen = false;
          }
          return newChange;
        }
        return node;
      }),
    );
  },
  getNode: (id: string) => {
    return get().nodes.find((node) => node.id === id);
  },
  currentAgentId: "",
  initialSetup: (nodes: AllNodeType[], agentId: string) => {
    useAgentStore.getState().unselectAll();
    set({
      currentAgentId: agentId,
    });
    const tweaks = JSON.parse(getLocalStorage(`lf_tweaks_${agentId}`) || "{}");
    set({
      nodes: getNodesWithDefaultValue(nodes, tweaks),
    });
    get().updateTweaks();
  },
  updateTweaks: () => {
    const nodes = get().nodes;
    const tweak = {};
    const agentId = get().currentAgentId;
    nodes.forEach((node) => {
      const nodeTemplate = node.data?.node?.template;
      if (nodeTemplate && node.type === "genericNode") {
        const currentTweak = {};
        Object.keys(nodeTemplate).forEach((name) => {
          if (!nodeTemplate[name].advanced) {
            currentTweak[name] = getChangesType(
              nodeTemplate[name].value,
              nodeTemplate[name],
            );
          }
        });
        if (Object.keys(currentTweak).length > 0) {
          tweak[node.id] = currentTweak;
        }
      }
    });
    setLocalStorage(`lf_tweaks_${agentId}`, JSON.stringify(tweak));
    set({
      tweaks: tweak,
    });
  },
}));
