import { useQueryClient } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { AgentType } from "@/types/agent";
import { processAgents } from "@/utils/reactFlowUtils";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IGetAgent {
  id: string;
  public?: boolean;
}

// add types for error handling and success
export const useGetAgent: useMutationFunctionType<undefined, IGetAgent> = (
  options,
) => {
  const { mutate } = UseRequestProcessor();
  const queryClient = useQueryClient();

  const getAgentFn = async (payload: IGetAgent): Promise<AgentType> => {
    const response = await api.get<AgentType>(
      `${getURL(payload.public ? "PUBLIC_FLOW" : "AGENTS")}/${payload.id}`,
    );

    const agentsArrayToProcess = [response.data];
    const { agents } = processAgents(agentsArrayToProcess);
    return agents[0];
  };

  const mutation = mutate(["useGetAgent"], getAgentFn, {
    ...options,
    onSettled: (response) => {
      if (response) {
        queryClient.refetchQueries({
          queryKey: [
            "useGetRefreshAgentsQuery",
            { get_all: true, header_agents: true },
          ],
        });
      }
    },
  });

  return mutation;
};
