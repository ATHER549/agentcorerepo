import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface ApprovalDetails {
  id: string;
  title: string;
  status: "pending" | "approved" | "rejected";
  description: string;
  submittedBy: {
    name: string;
    avatar?: string;
  };
  project: string;
  submitted: string;
  version: string;
  recentChanges: string;
  adminComments?: string | null;
  adminAttachments?: Array<{
    filename?: string;
    size?: number;
    uploadedAt?: string;
  }>;
}

export const useGetApprovalDetails: useQueryFunctionType<
  { agent_id: string },
  ApprovalDetails | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getDetailsFn = async (): Promise<ApprovalDetails | null> => {
    if (!params?.agent_id) return null;
    try {
      const res = await api.get<ApprovalDetails>(
        `${getURL("APPROVALS")}/${params.agent_id}`,
      );
      return res.data;
    } catch (e: any) {
      if (e?.response?.status === 404 || e?.response?.status === 403) {
        return null;
      }
      throw e;
    }
  };

  return query(["useGetApprovalDetails", params?.agent_id], getDetailsFn, {
    enabled: !!params?.agent_id,
    retry: false,
    ...options,
  });
};
