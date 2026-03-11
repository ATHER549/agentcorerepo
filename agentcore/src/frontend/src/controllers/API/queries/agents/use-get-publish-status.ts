import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface IPublishRecord {
  id: string;
  agent_id: string;
  version_number: string;
  agent_name: string;
  agent_description: string | null;
  publish_description: string | null;
  published_by: string;
  published_at: string;
  is_active: boolean;
  status: string;
  visibility: string;
  error_message: string | null;
  environment: "uat" | "prod";
  promoted_from_uat_id: string | null;
}

export interface IAgentPublishStatus {
  agent_id: string;
  uat: IPublishRecord | null;
  prod: IPublishRecord | null;
  has_pending_approval: boolean;
  pending_requested_by: string | null;
  latest_prod_status: string | null;
  latest_review_decision: string | null;
  latest_prod_published_by: string | null;
}

export interface IGetPublishStatusParams {
  agent_id: string;
}

export const useGetPublishStatus: useQueryFunctionType<
  IGetPublishStatusParams,
  IAgentPublishStatus | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getPublishStatusFn = async (): Promise<IAgentPublishStatus | null> => {
    if (!params?.agent_id) {
      return null;
    }

    const response = await api.get<IAgentPublishStatus>(
      `${getURL("PUBLISH")}/${params.agent_id}/status`,
    );
    return response.data;
  };

  const queryResult: UseQueryResult<IAgentPublishStatus | null> = query(
    ["useGetPublishStatus", params?.agent_id],
    getPublishStatusFn,
    {
      enabled: !!params?.agent_id,
      ...options,
    },
  );

  return queryResult;
};
