import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type ManagedPackage = {
  name: string;
  version_spec: string;
  resolved_version: string;
  source: Record<string, unknown>;
};

export const useGetManagedPackages: useQueryFunctionType<
  undefined,
  ManagedPackage[]
> = (options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getManagedPackagesFn = async (): Promise<ManagedPackage[]> => {
    if (!isAuthenticated) return [];
    const res = await api.get(`${getURL("PACKAGES")}/managed`);
    return res.data;
  };

  const queryResult: UseQueryResult<ManagedPackage[], any> = query(
    ["useGetManagedPackages"],
    getManagedPackagesFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
