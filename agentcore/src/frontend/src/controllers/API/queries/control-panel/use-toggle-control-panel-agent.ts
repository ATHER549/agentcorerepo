import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";

export interface ToggleControlPanelAgentPayload {
  deployId: string;
  env: "uat" | "prod";
  field: "is_active" | "is_enabled";
  value: boolean;
}

export interface ToggleControlPanelAgentResponse {
  deploy_id: string;
  field: "is_active" | "is_enabled" | string;
  new_value: boolean;
  registry_synced: boolean;
}

export const useToggleControlPanelAgent = () => {
  const queryClient = useQueryClient();

  return useMutation<
    ToggleControlPanelAgentResponse,
    Error,
    ToggleControlPanelAgentPayload
  >({
    mutationFn: async ({ deployId, env, field, value }) => {
      const res = await api.post<ToggleControlPanelAgentResponse>(
        `${getURL("CONTROL_PANEL")}/agents/${deployId}/toggle`,
        {
          env,
          field,
          value,
        },
      );
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetControlPanelAgents"] });
      queryClient.invalidateQueries({ queryKey: ["useGetRegistry"] });
    },
  });
};
