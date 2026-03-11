import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface OrchChatRequest {
  session_id: string;
  agent_id?: string | null;
  deployment_id?: string | null;
  input_value: string;
  version_number?: number | null;
}

export interface OrchMessageResponse {
  id: string;
  timestamp: string;
  sender: string;
  sender_name: string;
  session_id: string;
  text: string;
  agent_id: string | null;
  deployment_id: string | null;
  category?: string;
  properties?: {
    hitl?: boolean;
    thread_id?: string;
    actions?: string[];
    [key: string]: unknown;
  };
}

export interface OrchChatResponse {
  session_id: string;
  agent_name: string;
  message: OrchMessageResponse;
  context_reset: boolean;
}

export const useSendOrchMessage: useMutationFunctionType<
  undefined,
  OrchChatRequest,
  OrchChatResponse
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const sendMessageFn = async (
    payload: OrchChatRequest,
  ): Promise<OrchChatResponse> => {
    const response = await api.post<OrchChatResponse>(
      `${getURL("ORCHESTRATOR")}/chat`,
      payload,
    );
    return response.data;
  };

  const mutation: UseMutationResult<OrchChatResponse, any, OrchChatRequest> =
    mutate(["useSendOrchMessage"], sendMessageFn, {
      ...options,
      onSettled: () => {
        queryClient.invalidateQueries({
          queryKey: ["useGetOrchSessions"],
        });
      },
    });

  return mutation;
};
