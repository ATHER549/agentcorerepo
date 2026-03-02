import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
import type { OrchMessageResponse } from "./use-send-orch-message";

interface GetOrchMessagesParams {
  session_id: string;
}

export const useGetOrchMessages: useQueryFunctionType<
  GetOrchMessagesParams,
  OrchMessageResponse[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getOrchMessagesFn = async (): Promise<OrchMessageResponse[]> => {
    const res = await api.get<OrchMessageResponse[]>(
      `${getURL("ORCHESTRATOR")}/sessions/${encodeURIComponent(params.session_id)}/messages`,
    );
    return res.data;
  };

  return query(
    ["useGetOrchMessages", params.session_id],
    getOrchMessagesFn,
    options,
  );
};
