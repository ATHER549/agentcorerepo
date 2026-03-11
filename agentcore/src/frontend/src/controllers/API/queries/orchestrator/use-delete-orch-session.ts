import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface DeleteOrchSessionRequest {
  session_id: string;
}

export const useDeleteOrchSession: useMutationFunctionType<
  undefined,
  DeleteOrchSessionRequest,
  void
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const deleteSessionFn = async (
    payload: DeleteOrchSessionRequest,
  ): Promise<void> => {
    await api.delete(
      `${getURL("ORCHESTRATOR")}/sessions/${encodeURIComponent(payload.session_id)}`,
    );
  };

  const mutation: UseMutationResult<void, any, DeleteOrchSessionRequest> =
    mutate(["useDeleteOrchSession"], deleteSessionFn, {
      ...options,
      onSettled: () => {
        queryClient.invalidateQueries({
          queryKey: ["useGetOrchSessions"],
        });
      },
    });

  return mutation;
};
