import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import type { ModelCreateRequest, ModelType } from "@/types/models/models";

export const usePostRegistryModel = () => {
  const queryClient = useQueryClient();

  return useMutation<ModelType, Error, ModelCreateRequest>({
    mutationFn: async (data) => {
      const response = await api.post("api/models/registry/", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["registry-models"] });
    },
  });
};