import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface CancelHitlParams {
  thread_id: string;
}

/**
 * Hook to cancel a pending HITL run without resuming it.
 *
 * POST /api/v1/hitl/{thread_id}/cancel
 *
 * The frozen graph state remains in the checkpointer but the DB record is
 * marked as cancelled. The run cannot be resumed after cancellation.
 */
export const useCancelHitl: useMutationFunctionType<
  undefined,
  CancelHitlParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const cancelHitlFn = async (params: CancelHitlParams): Promise<void> => {
    await api.post(`${getURL("HITL")}/${params.thread_id}/cancel`, {});
  };

  const mutation: UseMutationResult<void, any, CancelHitlParams> = mutate(
    ["useCancelHitl"],
    cancelHitlFn,
    {
      ...options,
      onSettled: () => {
        queryClient.invalidateQueries({ queryKey: ["useGetHitlPending"] });
      },
    },
  );

  return mutation;
};
