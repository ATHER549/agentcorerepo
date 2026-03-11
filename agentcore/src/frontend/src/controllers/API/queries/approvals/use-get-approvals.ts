import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface ApprovalAgent {
  id: string;
  entityType?: "agent" | "model" | "mcp";
  title: string;
  status: "pending" | "approved" | "rejected";
  description: string;
  submittedBy: {
    name: string;
    avatar?: string;
    email?: string | null;
  };
  project: string;
  submitted: string;
  version: string;
  recentChanges: string;
}

/**
 * Hook to fetch all agents pending approval
 * Uses React Query for caching and automatic refetching
 */
export const useGetApprovals: useQueryFunctionType<undefined, ApprovalAgent[]> = (
  options?,
) => {
  const { query } = UseRequestProcessor();

  const getApprovalsFn = async (): Promise<ApprovalAgent[]> => {
    const res = await api.get(`${getURL("APPROVALS")}`);
    return res.data;
  };

  return query(["useGetApprovals"], getApprovalsFn, options);
};
