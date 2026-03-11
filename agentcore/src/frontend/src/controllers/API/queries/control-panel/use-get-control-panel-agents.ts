import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface ControlPanelAgentItem {
  deploy_id: string;
  agent_id: string;
  agent_name: string;
  agent_description?: string | null;
  version_number: string;
  status: string;
  visibility: "PUBLIC" | "PRIVATE" | string;
  is_active: boolean;
  is_enabled: boolean;
  creator_name?: string | null;
  creator_email?: string | null;
  owner_name?: string | null;
  owner_count?: number;
  owner_names?: string[];
  owner_emails?: string[];
  creator_department?: string | null;
  created_at: string;
  deployed_at?: string | null;
  last_run?: string | null;
  failed_runs: number;
  input_type: "chat" | "autonomous" | "file_processing";
  moved_to_prod?: boolean;
}

export interface ControlPanelAgentsResponse {
  items: ControlPanelAgentItem[];
  total: number;
  page: number;
  size: number;
}

interface GetControlPanelAgentsParams {
  env: "uat" | "prod";
  search?: string;
  page?: number;
  size?: number;
}

export const useGetControlPanelAgents: useQueryFunctionType<
  GetControlPanelAgentsParams,
  ControlPanelAgentsResponse
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getControlPanelAgentsFn =
    async (): Promise<ControlPanelAgentsResponse> => {
      const res = await api.get<ControlPanelAgentsResponse>(
        `${getURL("CONTROL_PANEL")}/agents`,
        {
          params: {
            env: params.env,
            search: params.search || undefined,
            page: params.page ?? 1,
            size: params.size ?? 20,
          },
        },
      );
      return res.data;
    };

  return query(
    [
      "useGetControlPanelAgents",
      params.env,
      params.search,
      params.page,
      params.size,
    ],
    getControlPanelAgentsFn,
    options,
  );
};
