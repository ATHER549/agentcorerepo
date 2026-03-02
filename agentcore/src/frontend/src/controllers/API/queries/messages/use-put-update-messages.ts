import type { UseMutationResult } from "@tanstack/react-query";
import { useGetAgentId } from "@/modals/IOModal/hooks/useGetAgentId";
import useAgentStore from "@/stores/agentStore";
import type { useMutationFunctionType } from "@/types/api";
import type { Message } from "@/types/messages";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface UpdateMessageParams {
  message: Partial<Message>;
  refetch?: boolean;
}

export const useUpdateMessage: useMutationFunctionType<
  undefined,
  UpdateMessageParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const agentId = useGetAgentId();

  const updateMessageApi = async (data: UpdateMessageParams) => {
    const isPlayground = useAgentStore.getState().playgroundPage;
    const message = data.message;
    if (message.files && typeof message.files === "string") {
      message.files = JSON.parse(message.files);
    }
    if (isPlayground && agentId) {
      const messages = JSON.parse(sessionStorage.getItem(agentId) || "");
      const messageIndex = messages.findIndex(
        (m: Message) => m.id === message.id,
      );
      messages[messageIndex] = {
        ...messages[messageIndex],
        ...message,
        agent_id: agentId,
      };
      sessionStorage.setItem(agentId, JSON.stringify(messages));
    } else {
      const result = await api.put(
        `${getURL("MESSAGES")}/${message.id}`,
        message,
      );
      return result.data;
    }
  };

  const mutation: UseMutationResult<Message, any, UpdateMessageParams> = mutate(
    ["useUpdateMessages"],
    updateMessageApi,
    {
      ...options,
      onSettled: (_, __, params, ___) => {
        //@ts-ignore
        if (params?.refetch && agentId) {
          queryClient.refetchQueries({
            queryKey: ["useGetMessagesQuery", { id: agentId }],
            exact: true,
          });
        }
      },
    },
  );

  return mutation;
};
