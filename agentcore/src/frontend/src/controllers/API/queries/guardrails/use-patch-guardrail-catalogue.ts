import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import type {
  GuardrailCreateOrUpdatePayload,
  GuardrailInfo,
} from "./use-get-guardrails-catalogue";

export const usePatchGuardrailCatalogue = () => {
  const queryClient = useQueryClient();

  return useMutation<
    GuardrailInfo,
    Error,
    { id: string; payload: GuardrailCreateOrUpdatePayload }
  >({
    mutationFn: async ({ id, payload }) => {
      const response = await api.patch(`${getURL("GUARDRAILS_CATALOGUE")}/${id}`, payload);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetGuardrailsCatalogue"] });
    },
  });
};
