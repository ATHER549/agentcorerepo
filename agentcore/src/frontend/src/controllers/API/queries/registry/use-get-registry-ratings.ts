import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface RegistryRatingItem {
  user_id: string;
  username?: string | null;
  score: number;
  review?: string | null;
  created_at: string;
}

export interface RegistryRatingsResponse {
  registry_id: string;
  average_rating?: number | null;
  total_ratings: number;
  items: RegistryRatingItem[];
}

interface GetRegistryRatingsParams {
  registry_id: string;
}

export const useGetRegistryRatings: useQueryFunctionType<
  GetRegistryRatingsParams,
  RegistryRatingsResponse | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getRegistryRatingsFn = async (): Promise<RegistryRatingsResponse | null> => {
    if (!params?.registry_id) return null;
    const res = await api.get<RegistryRatingsResponse>(
      `${getURL("REGISTRY")}/${params.registry_id}/ratings`,
    );
    return res.data;
  };

  return query(
    ["useGetRegistryRatings", params?.registry_id],
    getRegistryRatingsFn,
    {
      enabled: !!params?.registry_id,
      ...options,
    },
  );
};

