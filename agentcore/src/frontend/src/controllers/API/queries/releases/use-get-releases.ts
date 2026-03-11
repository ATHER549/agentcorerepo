import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type ReleaseRecord = {
  id: string;
  version: string;
  major: number;
  minor: number;
  patch: number;
  release_notes: string;
  start_date: string;
  end_date: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  is_active: boolean;
  package_count?: number;
};

export const useGetReleases: useQueryFunctionType<undefined, ReleaseRecord[]> = (
  options?,
) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getReleasesFn = async (): Promise<ReleaseRecord[]> => {
    if (!isAuthenticated) return [];
    const res = await api.get(`${getURL("RELEASES")}`);
    return res.data;
  };

  const queryResult: UseQueryResult<ReleaseRecord[], any> = query(
    ["useGetReleases"],
    getReleasesFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
