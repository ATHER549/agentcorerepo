import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface IPublishEmailSuggestion {
  email: string;
  display_name: string | null;
}

export interface IGetPublishEmailSuggestionsParams {
  agent_id: string;
  q: string;
  limit?: number;
}

export const useGetPublishEmailSuggestions: useQueryFunctionType<
  IGetPublishEmailSuggestionsParams,
  IPublishEmailSuggestion[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getSuggestionsFn = async (): Promise<IPublishEmailSuggestion[]> => {
    const agentId = params?.agent_id?.trim();
    const queryText = params?.q?.trim();
    if (!agentId || !queryText) {
      return [];
    }

    const response = await api.get<IPublishEmailSuggestion[]>(
      `${getURL("PUBLISH")}/${agentId}/email-suggestions`,
      {
        params: {
          q: queryText,
          limit: params?.limit ?? 8,
        },
      },
    );
    return response.data ?? [];
  };

  const queryResult: UseQueryResult<IPublishEmailSuggestion[]> = query(
    ["useGetPublishEmailSuggestions", params?.agent_id, params?.q, params?.limit ?? 8],
    getSuggestionsFn,
    {
      enabled: Boolean(params?.agent_id?.trim()) && Boolean(params?.q?.trim()),
      ...options,
    },
  );

  return queryResult;
};
