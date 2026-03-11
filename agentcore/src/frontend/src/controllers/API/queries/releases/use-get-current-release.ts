import type { UseQueryResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import { useDarkStore } from "@/stores/darkStore";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { ReleaseRecord } from "./use-get-releases";

export const useGetCurrentRelease: useQueryFunctionType<
  undefined,
  ReleaseRecord | null
> = (options?) => {
  const { query } = UseRequestProcessor();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getCurrentReleaseFn = async (): Promise<ReleaseRecord | null> => {
    if (!isAuthenticated) return null;
    const res = await api.get(`${getURL("RELEASES")}/current`);
    return res.data;
  };

  const responseFn = async (): Promise<ReleaseRecord | null> => {
    const data = await getCurrentReleaseFn();
    const refreshCurrentReleaseVersion = useDarkStore.getState().refreshCurrentReleaseVersion;
    refreshCurrentReleaseVersion(data?.version ?? "");
    return data;
  };

  const queryResult: UseQueryResult<ReleaseRecord | null, any> = query(
    ["useGetCurrentRelease"],
    responseFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
