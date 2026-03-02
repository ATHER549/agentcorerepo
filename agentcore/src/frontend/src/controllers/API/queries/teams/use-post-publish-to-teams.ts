import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type {
  TeamsPublishRequest,
  TeamsPublishResponse,
} from "@/types/teams";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const usePostPublishToTeams: useMutationFunctionType<
  TeamsPublishResponse,
  TeamsPublishRequest
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const publishToTeamsFn = async (
    payload: TeamsPublishRequest,
  ): Promise<TeamsPublishResponse> => {
    const response = await api.post<TeamsPublishResponse>(
      `${getURL("TEAMS")}/publish`,
      payload,
    );
    return response.data;
  };

  const mutation: UseMutationResult<
    TeamsPublishResponse,
    any,
    TeamsPublishRequest
  > = mutate(["usePostPublishToTeams"], publishToTeamsFn, {
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
