import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import type { ModelType, ModelUpdateRequest } from "@/types/models/models";

export const usePutRegistryModel = () => {
  const queryClient = useQueryClient();

  return useMutation<
    ModelType,
    Error,
    { id: string; data: ModelUpdateRequest }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.put(`api/models/registry/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["registry-models"] });
    },
  });
};