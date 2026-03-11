import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface ApproveAgentParams {
  agentId: string;
  comments: string;
  attachments?: File[];
}

/**
 * Hook to approve an agent
 * Sends approval request with optional comments to the backend
 */
export const useApproveAgent: useMutationFunctionType<
  undefined,
  ApproveAgentParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const approveAgentFn = async (
    params: ApproveAgentParams,
  ): Promise<void> => {
    const formData = new FormData();
    formData.append("comments", params.comments ?? "");
    for (const file of params.attachments ?? []) {
      formData.append("attachments", file);
    }

    await api.post(
      `${getURL("APPROVALS")}/${params.agentId}/approve`,
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
      },
    );
  };

  const mutation: UseMutationResult<
    void,
    any,
    ApproveAgentParams
  > = mutate(["useApproveAgent"], approveAgentFn, {
    ...options,
    onSettled: () => {
      // Refetch approvals list after approval
      queryClient.refetchQueries({ queryKey: ["useGetApprovals"] });
    },
  });

  return mutation;
};
