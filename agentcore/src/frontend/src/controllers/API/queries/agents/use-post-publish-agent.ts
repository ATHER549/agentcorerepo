import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface IPublishAgentRequest {
  agent_id: string;
  agentcore_url: string;
  agentcore_api_key: string;
  model_name?: string;
}

export interface IPublishAgentResponse {
  success: boolean;
  model_id: string;
  model_name: string;
  agentcore_url: string;
  pipe_function_deployed: boolean;
  message: string;
}

export const usePostPublishAgent: useMutationFunctionType<
  IPublishAgentResponse,
  IPublishAgentRequest
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const publishAgentFn = async (
    payload: IPublishAgentRequest,
  ): Promise<IPublishAgentResponse> => {
    const response = await api.post<IPublishAgentResponse>(
      `${getURL("PUBLISH")}/agentcore`,
      {
        agent_id: payload.agent_id,
        agentcore_url: payload.agentcore_url,
        agentcore_api_key: payload.agentcore_api_key,
        ...(payload.model_name && { model_name: payload.model_name }),
      },
    );
    return response.data;
  };

  const mutation: UseMutationResult<
    IPublishAgentResponse,
    any,
    IPublishAgentRequest
  > = mutate(["usePostPublishAgent"], publishAgentFn, {
    ...options,
    onSettled: (response) => {
      if (response?.agent_id) {
        // Refetch publish status for this agent
        queryClient.invalidateQueries({
          queryKey: ["useGetPublishStatus", response.agent_id],
        });
      }
    },
  });

  return mutation;
};
