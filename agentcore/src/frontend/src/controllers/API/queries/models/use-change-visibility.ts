import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import type { ModelType } from "@/types/models/models";

interface ChangeVisibilityPayload {
  id: string;
  visibility_scope: string;
}

export const useChangeModelVisibility = () => {
  const queryClient = useQueryClient();

  return useMutation<ModelType, Error, ChangeVisibilityPayload>({
    mutationFn: async ({ id, visibility_scope }) => {
      const response = await api.post(
        `api/models/registry/${id}/visibility`,
        { visibility_scope },
      );
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["registry-models"] });
    },
  });
};
