import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface GuardrailVersion {
  id: string;
  guardrail_id: string;
  version_number: number;
  guardrail_name: string;
  guardrail_snapshot: Record<string, any>;
  is_active: boolean;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface GuardrailVersionListResponse {
  versions: GuardrailVersion[];
}

export interface GuardrailVersionsParams {
  guardrailId: string;
}

export const useGetGuardrailVersions: useQueryFunctionType<
  GuardrailVersionsParams,
  GuardrailVersionListResponse
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getGuardrailVersionsFn =
    async (): Promise<GuardrailVersionListResponse> => {
      const res = await api.get(
        `${getURL("GUARDRAILS_CATALOGUE")}/${params?.guardrailId}/versions`,
      );
      return res.data ?? { versions: [] };
    };

  const queryResult: UseQueryResult<GuardrailVersionListResponse, any> = query(
    ["useGetGuardrailVersions", params?.guardrailId ?? ""],
    getGuardrailVersionsFn,
    {
      enabled: !!params?.guardrailId,
      refetchOnMount: true,
      ...options,
    },
  );

  return queryResult;
};
