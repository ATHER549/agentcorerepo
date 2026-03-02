import { useUpdateNodeInternals } from "@xyflow/react";
import { cloneDeep } from "lodash";
import useAgentStore from "@/stores/agentStore";
import type { AllNodeType } from "@/types/agent";

const useHandleNodeClass = (
  nodeId: string,
  setMyNode?: (
    id: string,
    update: AllNodeType | ((oldState: AllNodeType) => AllNodeType),
  ) => void,
) => {
  const setNode = setMyNode ?? useAgentStore((state) => state.setNode);
  const updateNodeInternals = useUpdateNodeInternals();

  const handleNodeClass = (newNodeClass, type?: string) => {
    setNode(nodeId, (oldNode) => {
      const newNode = cloneDeep(oldNode);

      newNode.data = {
        ...newNode.data,
        node: cloneDeep(newNodeClass),
      };
      if (type) {
        newNode.data.type = type;
      }

      updateNodeInternals(nodeId);

      return newNode;
    });
  };

  return { handleNodeClass };
};

export default useHandleNodeClass;
