import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface RateRegistryRequest {
  registry_id: string;
  score: number;
  review?: string;
}

interface RateRegistryResponse {
  registry_id: string;
  user_id: string;
  score: number;
  review?: string | null;
  new_average: number;
  new_count: number;
}

export const usePostRegistryRate: useMutationFunctionType<
  undefined,
  RateRegistryRequest,
  RateRegistryResponse
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const rateRegistryFn = async (
    params: RateRegistryRequest,
  ): Promise<RateRegistryResponse> => {
    const res = await api.post<RateRegistryResponse>(
      `${getURL("REGISTRY")}/${params.registry_id}/rate`,
      {
        score: params.score,
        review: params.review || undefined,
      },
    );
    return res.data;
  };

  return mutate(["usePostRegistryRate"], rateRegistryFn, {
    ...options,
    onSuccess: (data, variables, context) => {
      queryClient.invalidateQueries({ queryKey: ["useGetRegistry"] });
      queryClient.invalidateQueries({
        queryKey: ["useGetRegistryRatings", variables.registry_id],
      });
      options?.onSuccess?.(data, variables, context);
    },
  });
};

