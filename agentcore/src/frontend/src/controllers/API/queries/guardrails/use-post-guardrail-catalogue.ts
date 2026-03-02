import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import type {
  GuardrailCreateOrUpdatePayload,
  GuardrailInfo,
} from "./use-get-guardrails-catalogue";

export const usePostGuardrailCatalogue = () => {
  const queryClient = useQueryClient();

  return useMutation<GuardrailInfo, Error, GuardrailCreateOrUpdatePayload>({
    mutationFn: async (payload) => {
      const response = await api.post(`${getURL("GUARDRAILS_CATALOGUE")}/`, payload);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetGuardrailsCatalogue"] });
    },
  });
};
