import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type TransitivePackage = {
  id: string;
  name: string;
  resolved_version: string;
  required_by: string[];
  required_by_details: { name: string; version: string }[];
  start_date: string;
  end_date: string;
  is_current: boolean;
  source: Record<string, unknown>;
};

export const useGetTransitivePackages: useQueryFunctionType<
  undefined,
  TransitivePackage[]
> = (options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getTransitivePackagesFn = async (): Promise<TransitivePackage[]> => {
    if (!isAuthenticated) return [];
    const res = await api.get(`${getURL("PACKAGES")}/transitive`);
    return res.data;
  };

  const queryResult: UseQueryResult<TransitivePackage[], any> = query(
    ["useGetTransitivePackages"],
    getTransitivePackagesFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
