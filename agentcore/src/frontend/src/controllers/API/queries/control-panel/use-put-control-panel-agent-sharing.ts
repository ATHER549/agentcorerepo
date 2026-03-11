import type { UseMutationResult } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { ControlPanelSharingResponse } from "./use-get-control-panel-agent-sharing";

export interface UpdateControlPanelAgentSharingPayload {
  deploy_id: string;
  recipient_emails: string[];
}

export const usePutControlPanelAgentSharing = (options?: any) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const fn = async (
    payload: UpdateControlPanelAgentSharingPayload,
  ): Promise<ControlPanelSharingResponse> => {
    const res = await api.put<ControlPanelSharingResponse>(
      `${getURL("CONTROL_PANEL")}/agents/${payload.deploy_id}/sharing`,
      { recipient_emails: payload.recipient_emails },
    );
    return res.data;
  };

  return mutate(["usePutControlPanelAgentSharing"], fn, {
    ...options,
    onSettled: (...args) => {
      queryClient.invalidateQueries({ queryKey: ["useGetControlPanelAgents"] });
      options?.onSettled?.(...args);
    },
  }) as UseMutationResult<ControlPanelSharingResponse, any, UpdateControlPanelAgentSharingPayload>;
};
