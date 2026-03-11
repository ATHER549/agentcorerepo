import type { UseMutationResult } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { ReleaseRecord } from "./use-get-releases";

export type ReleaseBumpPayload = {
  bump_type: "major" | "minor" | "patch";
  release_notes?: string;
};

export const usePostBumpRelease = (options?: any) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const bumpReleaseFn = async (
    payload: ReleaseBumpPayload,
  ): Promise<ReleaseRecord> => {
    const res = await api.post(`${getURL("RELEASES")}/bump`, payload);
    return res.data;
  };

  return mutate(["usePostBumpRelease"], bumpReleaseFn, {
    ...options,
    onSettled: (...args) => {
      queryClient.invalidateQueries({ queryKey: ["useGetCurrentRelease"] });
      queryClient.invalidateQueries({ queryKey: ["useGetReleases"] });
      options?.onSettled?.(...args);
    },
  }) as UseMutationResult<ReleaseRecord, any, ReleaseBumpPayload>;
};
