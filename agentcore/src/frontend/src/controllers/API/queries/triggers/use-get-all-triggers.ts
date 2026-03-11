import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface TriggerInfo {
  id: string;
  agent_id: string;
  agent_name: string;
  deployment_id: string | null;
  trigger_type: "schedule" | "folder_monitor" | "email_monitor";
  trigger_config: Record<string, any>;
  is_active: boolean;
  environment: string;
  version: string | null;
  last_triggered_at: string | null;
  trigger_count: number;
  created_at: string;
  updated_at: string;
}

export const useGetAllTriggers: useQueryFunctionType<
  { triggerType?: string } | undefined,
  TriggerInfo[]
> = (params?, options?) => {
  const { query } = UseRequestProcessor();

  const getAllTriggersFn = async (): Promise<TriggerInfo[]> => {
    const queryParams = params?.triggerType
      ? `?trigger_type=${params.triggerType}`
      : "";
    const res = await api.get(`${getURL("TRIGGERS")}/${queryParams}`);
    return res.data ?? [];
  };

  const queryResult: UseQueryResult<TriggerInfo[], any> = query(
    ["useGetAllTriggers", params?.triggerType],
    getAllTriggersFn,
    {
      refetchOnWindowFocus: false,
      refetchInterval: 30_000,  // keep Runs / Last Run columns live on the table
      ...options,
    },
  );

  return queryResult;
};
