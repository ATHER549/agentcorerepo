import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface DelegateHitlParams {
  thread_id: string;
  delegate_to_user_id: string;
}

export interface DelegateHitlResponse {
  status: "delegated";
  thread_id: string;
  delegated_to: string;
}

/**
 * Hook to delegate a pending HITL request to another user.
 *
 * POST /api/v1/hitl/{thread_id}/delegate
 * Body: { delegate_to_user_id }
 *
 * Invalidates the pending list so the table refreshes after delegation.
 */
export const useDelegateHitl: useMutationFunctionType<
  undefined,
  DelegateHitlParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const delegateHitlFn = async (
    params: DelegateHitlParams,
  ): Promise<DelegateHitlResponse> => {
    const res = await api.post<DelegateHitlResponse>(
      `${getURL("HITL")}/${params.thread_id}/delegate`,
      {
        delegate_to_user_id: params.delegate_to_user_id,
      },
    );
    return res.data;
  };

  const mutation: UseMutationResult<
    DelegateHitlResponse,
    any,
    DelegateHitlParams
  > = mutate(["useDelegateHitl"], delegateHitlFn, {
    ...options,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetHitlPending"] });
    },
  });

  return mutation;
};
