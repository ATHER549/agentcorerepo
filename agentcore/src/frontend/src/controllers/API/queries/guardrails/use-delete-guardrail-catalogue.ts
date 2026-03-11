import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";

export const useDeleteGuardrailCatalogue = () => {
  const queryClient = useQueryClient();

  return useMutation<void, Error, { id: string }>({
    mutationFn: async ({ id }) => {
      await api.delete(`${getURL("GUARDRAILS_CATALOGUE")}/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetGuardrailsCatalogue"] });
    },
  });
};
