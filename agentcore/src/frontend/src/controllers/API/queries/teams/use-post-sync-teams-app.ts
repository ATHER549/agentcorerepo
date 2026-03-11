import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { TeamsPublishResponse } from "@/types/teams";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface SyncParams {
  agent_id: string;
}

export const usePostSyncTeamsApp: useMutationFunctionType<
  TeamsPublishResponse,
  SyncParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const syncFn = async (
    payload: SyncParams,
  ): Promise<TeamsPublishResponse> => {
    const response = await api.post<TeamsPublishResponse>(
      `${getURL("TEAMS")}/sync/${payload.agent_id}`,
    );
    return response.data;
  };

  const mutation: UseMutationResult<
    TeamsPublishResponse,
    any,
    SyncParams
  > = mutate(["usePostSyncTeamsApp"], syncFn, {
    ...options,
    onSettled: (response) => {
      if (response?.agent_id) {
        queryClient.invalidateQueries({
          queryKey: ["useGetTeamsStatus", response.agent_id],
        });
      }
    },
  });

  return mutation;
};
