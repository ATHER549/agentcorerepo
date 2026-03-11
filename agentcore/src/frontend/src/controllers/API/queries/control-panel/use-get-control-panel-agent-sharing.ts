import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface ControlPanelSharingResponse {
  deploy_id: string;
  agent_id: string;
  department_id: string | null;
  recipient_emails: string[];
}

interface GetControlPanelAgentSharingParams {
  deploy_id: string;
}

export const useGetControlPanelAgentSharing: useQueryFunctionType<
  GetControlPanelAgentSharingParams,
  ControlPanelSharingResponse | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const fn = async (): Promise<ControlPanelSharingResponse | null> => {
    if (!params?.deploy_id) return null;
    const res = await api.get<ControlPanelSharingResponse>(
      `${getURL("CONTROL_PANEL")}/agents/${params.deploy_id}/sharing`,
    );
    return res.data;
  };

  return query(["useGetControlPanelAgentSharing", params?.deploy_id], fn, {
    enabled: Boolean(params?.deploy_id),
    ...options,
  });
};
