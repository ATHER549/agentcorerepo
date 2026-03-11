import type { UseMutationResult } from "@tanstack/react-query";
import { useGetAgentId } from "@/modals/IOModal/hooks/useGetAgentId";
import useAgentStore from "@/stores/agentStore";
import type { useMutationFunctionType } from "@/types/api";
import type { Message } from "@/types/messages";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface UpdateSessionParams {
  old_session_id: string;
  new_session_id: string;
}

export const useUpdateSessionName: useMutationFunctionType<
  undefined,
  UpdateSessionParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const agentId = useGetAgentId();

  const updateSessionApi = async (data: UpdateSessionParams) => {
    const isPlayground = useAgentStore.getState().playgroundPage;
    // if we are in playground we will edit the local storage instead of the API
    if (isPlayground && agentId) {
      const messages = JSON.parse(sessionStorage.getItem(agentId) || "");
      const messagesWithNewSessionId = messages.map((message: Message) => {
        if (message.session_id === data.old_session_id) {
          message.session_id = data.new_session_id;
        }
        return message;
      });
      sessionStorage.setItem(agentId, JSON.stringify(messagesWithNewSessionId));
      return {
        data: messagesWithNewSessionId,
      };
    } else {
      const result = await api.patch(
        `${getURL("MESSAGES")}/session/${data.old_session_id}`,
        null,
        {
          params: { new_session_id: data.new_session_id },
        },
      );
      return result.data;
    }
  };

  const mutation: UseMutationResult<Message[], any, UpdateSessionParams> =
    mutate(["useUpdateSessionName"], updateSessionApi, {
      ...options,
      onSettled: () => {
        queryClient.invalidateQueries({
          queryKey: ["useGetSessionsFromAgentQuery"],
        });
      },
    });

  return mutation;
};
