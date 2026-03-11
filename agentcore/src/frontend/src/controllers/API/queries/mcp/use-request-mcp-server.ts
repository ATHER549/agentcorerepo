import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import type { McpRegistryType, McpRegistryCreateRequest } from "@/types/mcp";

export const useRequestMCPServer = () => {
  const queryClient = useQueryClient();

  return useMutation<McpRegistryType, Error, McpRegistryCreateRequest>({
    mutationFn: async (data) => {
      const response = await api.post("api/mcp/registry/request", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-registry"] });
      queryClient.invalidateQueries({ queryKey: ["useGetApprovals"] });
    },
  });
};
