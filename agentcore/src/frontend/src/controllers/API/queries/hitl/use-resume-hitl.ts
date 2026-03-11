import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface ResumeHitlParams {
  thread_id: string;
  action: string;
  feedback?: string;
  edited_value?: string;
}

export interface ResumeHitlResponse {
  status: "completed" | "interrupted";
  thread_id: string;
  action?: string;
  interrupt_data?: Record<string, unknown>;
  hitl_request_id?: string;
}

/**
 * Hook to resume a paused HITL run with a human decision.
 *
 * POST /api/v1/hitl/{thread_id}/resume
 * Body: { action, feedback?, edited_value? }
 *
 * Invalidates the pending list so the table refreshes after approval/rejection.
 */
export const useResumeHitl: useMutationFunctionType<
  undefined,
  ResumeHitlParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const resumeHitlFn = async (
    params: ResumeHitlParams,
  ): Promise<ResumeHitlResponse> => {
    const res = await api.post<ResumeHitlResponse>(
      `${getURL("HITL")}/${params.thread_id}/resume`,
      {
        action: params.action,
        feedback: params.feedback ?? "",
        edited_value: params.edited_value ?? "",
      },
    );
    return res.data;
  };

  const mutation: UseMutationResult<
    ResumeHitlResponse,
    any,
    ResumeHitlParams
  > = mutate(["useResumeHitl"], resumeHitlFn, {
    ...options,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetHitlPending"] });
      // Re-fetch playground messages so the ChatOutput response appears after resume.
      queryClient.invalidateQueries({ queryKey: ["useGetMessagesQuery"] });
    },
  });

  return mutation;
};
