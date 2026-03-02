import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { TeamsOAuthStatusResponse } from "@/types/teams";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useGetTeamsOAuthStatus: useMutationFunctionType<
  TeamsOAuthStatusResponse,
  void
> = (options?) => {
  const { mutate } = UseRequestProcessor();

  const getOAuthStatusFn = async (): Promise<TeamsOAuthStatusResponse> => {
    const response = await api.get<TeamsOAuthStatusResponse>(
      `${getURL("TEAMS")}/oauth/status`,
    );
    return response.data;
  };

  const mutation: UseMutationResult<
    TeamsOAuthStatusResponse,
    any,
    void
  > = mutate(["useGetTeamsOAuthStatus"], getOAuthStatusFn, options);

  return mutation;
};
