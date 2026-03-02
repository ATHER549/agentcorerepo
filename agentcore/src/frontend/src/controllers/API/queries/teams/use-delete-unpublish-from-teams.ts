import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { TeamsPublishResponse } from "@/types/teams";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface UnpublishParams {
  agent_id: string;
}

export const useDeleteUnpublishFromTeams: useMutationFunctionType<
  TeamsPublishResponse,
  UnpublishParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const unpublishFn = async (
    payload: UnpublishParams,
  ): Promise<TeamsPublishResponse> => {
    const response = await api.delete<TeamsPublishResponse>(
      `${getURL("TEAMS")}/unpublish/${payload.agent_id}`,
    );
    return response.data;
  };

  const mutation: UseMutationResult<
    TeamsPublishResponse,
    any,
    UnpublishParams
  > = mutate(["useDeleteUnpublishFromTeams"], unpublishFn, {
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
