import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import type { McpRegistryType, McpRegistryUpdateRequest } from "@/types/mcp";

export const usePatchMCPServer = () => {
  const queryClient = useQueryClient();

  return useMutation<
    McpRegistryType,
    Error,
    { id: string; data: McpRegistryUpdateRequest }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.put(`api/mcp/registry/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-registry"] });
    },
  });
};
