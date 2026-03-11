import type { UseMutationResult } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface PromoteControlPanelAgentPayload {
  deploy_id: string;
  visibility?: "PUBLIC" | "PRIVATE";
  publish_description?: string;
  recipient_emails?: string[];
}

export interface PromoteControlPanelAgentResponse {
  success: boolean;
  message: string;
  publish_id: string;
  environment: "uat" | "prod";
  status: string;
  is_active: boolean;
  version_number: string;
}

export const usePostControlPanelPromote = (options?: any) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const fn = async (
    payload: PromoteControlPanelAgentPayload,
  ): Promise<PromoteControlPanelAgentResponse> => {
    const res = await api.post<PromoteControlPanelAgentResponse>(
      `${getURL("CONTROL_PANEL")}/agents/${payload.deploy_id}/promote`,
      {
        visibility: payload.visibility ?? "PRIVATE",
        publish_description: payload.publish_description ?? null,
        recipient_emails: payload.recipient_emails ?? [],
      },
    );
    return res.data;
  };

  return mutate(["usePostControlPanelPromote"], fn, {
    ...options,
    onSettled: (...args) => {
      queryClient.invalidateQueries({ queryKey: ["useGetControlPanelAgents"] });
      options?.onSettled?.(...args);
    },
  }) as UseMutationResult<
    PromoteControlPanelAgentResponse,
    any,
    PromoteControlPanelAgentPayload
  >;
};
