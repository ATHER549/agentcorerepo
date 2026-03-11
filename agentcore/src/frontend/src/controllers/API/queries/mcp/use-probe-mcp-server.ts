import { useMutation } from "@tanstack/react-query";
import { api } from "../../api";
import type { McpProbeResponse } from "@/types/mcp";

export const useProbeMCPServer = () => {
  return useMutation<McpProbeResponse, Error, { id: string }>({
    mutationFn: async ({ id }) => {
      const response = await api.post(`api/mcp/registry/${id}/probe`);
      return response.data;
    },
  });
};
