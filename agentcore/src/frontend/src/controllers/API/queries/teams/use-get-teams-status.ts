import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { TeamsAppStatusResponse } from "@/types/teams";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface GetStatusParams {
  agent_id: string;
}

export const useGetTeamsStatus: useMutationFunctionType<
  TeamsAppStatusResponse,
  GetStatusParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const getStatusFn = async (
    payload: GetStatusParams,
  ): Promise<TeamsAppStatusResponse> => {
    const response = await api.get<TeamsAppStatusResponse>(
      `${getURL("TEAMS")}/status/${payload.agent_id}`,
    );
    return response.data;
  };

  const mutation: UseMutationResult<
    TeamsAppStatusResponse,
    any,
    GetStatusParams
  > = mutate(["useGetTeamsStatus"], getStatusFn, options);

  return mutation;
};
