import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import type { McpRegistryType } from "@/types/mcp";

export const useGetMCPServer = (serverId: string | undefined) => {
  return useQuery<McpRegistryType>({
    queryKey: ["mcp-registry", serverId],
    queryFn: async () => {
      const response = await api.get(`api/mcp/registry/${serverId}`);
      return response.data;
    },
    enabled: !!serverId,
  });
};
