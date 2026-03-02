import useAgentStore from "../stores/agentStore";
import useAgentsManagerStore from "../stores/agentsManagerStore";
import { customStringify } from "../utils/reactFlowUtils";

export function useUnsavedChanges() {
  const currentAgent = useAgentStore((state) => state.currentAgent);
  const savedAgent = useAgentsManagerStore((state) => state.currentAgent);

  if (!currentAgent || !savedAgent) {
    return false;
  }

  return customStringify(currentAgent) !== customStringify(savedAgent);
}
