import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface OrchSessionSummary {
  session_id: string;
  last_timestamp: string | null;
  preview: string;
  active_agent_id: string | null;
  active_deployment_id: string | null;
  active_agent_name: string | null;
}

export const useGetOrchSessions: useQueryFunctionType<
  undefined,
  OrchSessionSummary[]
> = (options?) => {
  const { query } = UseRequestProcessor();

  const getOrchSessionsFn = async (): Promise<OrchSessionSummary[]> => {
    const res = await api.get<OrchSessionSummary[]>(
      `${getURL("ORCHESTRATOR")}/sessions`,
    );
    return res.data;
  };

  return query(["useGetOrchSessions"], getOrchSessionsFn, options);
};
