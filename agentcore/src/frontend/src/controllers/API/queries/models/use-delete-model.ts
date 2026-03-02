import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";

export const useDeleteRegistryModel = () => {
  const queryClient = useQueryClient();

  return useMutation<void, Error, { id: string }>({
    mutationFn: async ({ id }) => {
      await api.delete(`api/models/registry/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["registry-models"] });
    },
  });
};