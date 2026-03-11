import { useEffect } from "react";
import type { VertexBuildTypeAPI } from "@/types/api";
import type { AgentPoolType } from "../../types/zustand/agent";

const useUpdateValidationStatus = (
  dataId: string,
  agentPool: AgentPoolType,
  setValidationStatus: (value: any) => void,
  getValidationStatus: (data) => VertexBuildTypeAPI | null,
) => {
  useEffect(() => {
    const relevantData =
      agentPool[dataId] && agentPool[dataId]?.length > 0
        ? agentPool[dataId][agentPool[dataId].length - 1]
        : null;
    if (relevantData) {
      // Extract validation information from relevantData and update the validationStatus state
      setValidationStatus(relevantData);
    } else {
      setValidationStatus(null);
    }
    getValidationStatus(relevantData);
  }, [agentPool[dataId], dataId, setValidationStatus]);
};

export default useUpdateValidationStatus;
