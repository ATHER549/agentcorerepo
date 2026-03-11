import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import type { McpRegistryType } from "@/types/mcp";

export const useGetMCPServers = (params?: { active_only?: boolean }) => {
  return useQuery<McpRegistryType[]>({
    queryKey: ["mcp-registry", params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params?.active_only !== undefined)
        searchParams.set("active_only", String(params.active_only));

      const qs = searchParams.toString();
      const url = `api/mcp/registry/${qs ? `?${qs}` : ""}`;
      const response = await api.get(url);
      return response.data;
    },
    refetchOnMount: true,
  });
};
