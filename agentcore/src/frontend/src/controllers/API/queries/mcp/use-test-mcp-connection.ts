import { useMutation } from "@tanstack/react-query";
import { api } from "../../api";
import type {
  McpTestConnectionRequest,
  McpTestConnectionResponse,
} from "@/types/mcp";

export const useTestMCPConnection = () => {
  return useMutation<McpTestConnectionResponse, Error, McpTestConnectionRequest>(
    {
      mutationFn: async (body) => {
        const response = await api.post(
          "api/mcp/registry/test-connection",
          body,
        );
        return response.data;
      },
    },
  );
};
