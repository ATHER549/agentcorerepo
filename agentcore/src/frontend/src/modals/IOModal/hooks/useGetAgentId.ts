import { v5 as uuidv5 } from "uuid";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useUtilityStore } from "@/stores/utilityStore";

export const useGetAgentId = () => {
  const clientId = useUtilityStore((state) => state.clientId);
  const realAgentId = useAgentsManagerStore((state) => state.currentAgentId);
  const playgroundPage = useAgentStore((state) => state.playgroundPage);
  const currentAgentId = playgroundPage
    ? uuidv5(`${clientId}_${realAgentId}`, uuidv5.DNS)
    : realAgentId;
  return currentAgentId;
};
