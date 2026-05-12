import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface VersionAgentInfo {
  agent_id: string;
  agent_name: string;
  deployment_version: string;
  deployed_at: string | null;
}

export interface VersionAgentsResponse {
  guardrail_id: string;
  version_agents: Record<string, VersionAgentInfo[]>;
}

export interface VersionAgentsParams {
  guardrailId: string;
}

export const useGetGuardrailVersionAgents: useQueryFunctionType<
  VersionAgentsParams,
  VersionAgentsResponse
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getVersionAgentsFn =
    async (): Promise<VersionAgentsResponse> => {
      const res = await api.get(
        `${getURL("GUARDRAILS_CATALOGUE")}/${params?.guardrailId}/version-agents`,
      );
      return res.data ?? { guardrail_id: "", version_agents: {} };
    };

  const queryResult: UseQueryResult<VersionAgentsResponse, any> = query(
    ["useGetGuardrailVersionAgents", params?.guardrailId ?? ""],
    getVersionAgentsFn,
    {
      enabled: !!params?.guardrailId,
      refetchOnMount: true,
      ...options,
    },
  );

  return queryResult;
};
