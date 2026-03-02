import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface IUnpublishAgentRequest {
  agent_id: string;
  agentcore_url: string;
  agentcore_api_key: string;
}

export interface IUnpublishAgentResponse {
  success: boolean;
  message: string;
  agent_id: string;
  platform_url: string;
}

export const useDeleteUnpublishAgent: useMutationFunctionType<
  IUnpublishAgentResponse,
  IUnpublishAgentRequest
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const unpublishAgentFn = async (
    payload: IUnpublishAgentRequest,
  ): Promise<IUnpublishAgentResponse> => {
    const response = await api.delete<IUnpublishAgentResponse>(
      `${getURL("PUBLISH")}/agentcore`,
      {
        data: {
          agent_id: payload.agent_id,
          agentcore_url: payload.agentcore_url,
          agentcore_api_key: payload.agentcore_api_key,
        },
      },
    );
    return response.data;
  };

  const mutation: UseMutationResult<
    IUnpublishAgentResponse,
    any,
    IUnpublishAgentRequest
  > = mutate(["useDeleteUnpublishAgent"], unpublishAgentFn, {
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
