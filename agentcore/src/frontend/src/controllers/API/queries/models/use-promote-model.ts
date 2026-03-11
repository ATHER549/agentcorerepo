import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import type { ModelType } from "@/types/models/models";

interface PromoteModelPayload {
  id: string;
  target_environment: string;
}

export const usePromoteRegistryModel = () => {
  const queryClient = useQueryClient();

  return useMutation<ModelType, Error, PromoteModelPayload>({
    mutationFn: async ({ id, target_environment }) => {
      const response = await api.post(`api/models/registry/${id}/promote`, {
        target_environment,
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["registry-models"] });
    },
  });
};
