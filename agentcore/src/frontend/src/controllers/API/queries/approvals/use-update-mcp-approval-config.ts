import type { UseMutationResult } from "@tanstack/react-query";
import type { McpRegistryType, McpRegistryUpdateRequest } from "@/types/mcp";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface Params {
  approvalId: string;
  data: McpRegistryUpdateRequest;
}

export const useUpdateMcpApprovalConfig = (options?: any) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const updateFn = async (params: Params): Promise<McpRegistryType> => {
    const res = await api.put<McpRegistryType>(
      `${getURL("APPROVALS")}/${params.approvalId}/mcp-config`,
      params.data,
    );
    return res.data;
  };

  const mutation: UseMutationResult<McpRegistryType, any, Params> = mutate(
    ["useUpdateMcpApprovalConfig"],
    updateFn,
    {
      ...options,
      onSettled: () => {
        queryClient.refetchQueries({ queryKey: ["useGetApprovals"] });
      },
    },
  );

  return mutation;
};
