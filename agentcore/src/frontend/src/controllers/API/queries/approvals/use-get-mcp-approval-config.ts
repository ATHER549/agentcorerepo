import type { useQueryFunctionType } from "@/types/api";
import type { McpRegistryType } from "@/types/mcp";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface Params {
  approval_id: string;
}

export const useGetMcpApprovalConfig: useQueryFunctionType<
  Params,
  McpRegistryType | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getConfigFn = async (): Promise<McpRegistryType | null> => {
    if (!params?.approval_id) return null;
    try {
      const res = await api.get<McpRegistryType>(
        `${getURL("APPROVALS")}/${params.approval_id}/mcp-config`,
      );
      return res.data;
    } catch (e: any) {
      if (e?.response?.status === 404 || e?.response?.status === 403) {
        return null;
      }
      throw e;
    }
  };

  return query(["useGetMcpApprovalConfig", params?.approval_id], getConfigFn, {
    enabled: !!params?.approval_id,
    retry: false,
    ...options,
  });
};
