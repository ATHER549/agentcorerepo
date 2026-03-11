import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface ApprovalPreviewResponse {
  id: string;
  title: string;
  version: string;
  snapshot: Record<string, any>;
}

interface GetApprovalPreviewParams {
  agent_id: string;
}

export const useGetApprovalPreview: useQueryFunctionType<
  GetApprovalPreviewParams,
  ApprovalPreviewResponse | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getApprovalPreviewFn = async (): Promise<ApprovalPreviewResponse | null> => {
    if (!params?.agent_id) return null;

    const res = await api.get<ApprovalPreviewResponse>(
      `${getURL("APPROVALS")}/${params.agent_id}/preview`,
    );
    return res.data;
  };

  return query(
    ["useGetApprovalPreview", params?.agent_id],
    getApprovalPreviewFn,
    {
      enabled: !!params?.agent_id,
      ...options,
    },
  );
};
