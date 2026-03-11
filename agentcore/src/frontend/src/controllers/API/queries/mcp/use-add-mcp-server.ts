import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import type { McpRegistryType, McpRegistryCreateRequest } from "@/types/mcp";

export const useAddMCPServer = () => {
  const queryClient = useQueryClient();

  return useMutation<McpRegistryType, Error, McpRegistryCreateRequest>({
    mutationFn: async (data) => {
      const response = await api.post("api/mcp/registry/", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-registry"] });
    },
  });
};
