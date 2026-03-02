import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import type { TimeoutSetting } from "./use-get-timeout-settings";

export const usePutTimeoutSettings = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: TimeoutSetting[]) => {
      const response = await api.put(`${getURL("TIMEOUT_SETTINGS")}/`, payload);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["timeout-settings"] });
    },
  });
};
