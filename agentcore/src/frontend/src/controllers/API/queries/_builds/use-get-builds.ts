import { keepPreviousData } from "@tanstack/react-query";
import type { AxiosResponse } from "axios";
import { useParams } from "react-router-dom";
import useAgentStore from "@/stores/agentStore";
import type { AgentPoolType } from "@/types/zustand/agent";
import type { useQueryFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface BuildsQueryParams {
  agentId?: string;
}

export const useGetBuildsQuery: useQueryFunctionType<
  BuildsQueryParams,
  AxiosResponse<{ vertex_builds: AgentPoolType }>
> = (params) => {
  const { query } = UseRequestProcessor();
  const { id: routeAgentId } = useParams();
  const resolvedAgentId =
    !params.agentId || params.agentId === "" ? routeAgentId : params.agentId;

  const setAgentPool = useAgentStore((state) => state.setAgentPool);
  const currentAgent = useAgentStore((state) => state.currentAgent);

  const responseFn = async () => {
    const config = {};
    config["params"] = {
      agent_id: resolvedAgentId,
    };

    const response = await api.get<any>(`${getURL("BUILDS")}`, config);

    if (currentAgent) {
      const agentPool = response.data.vertex_builds;
      setAgentPool(agentPool);
    }

    return response;
  };

  const queryResult = query(
    ["useGetBuildsQuery", { key: resolvedAgentId }],
    responseFn,
    {
      placeholderData: keepPreviousData,
      refetchOnWindowFocus: false,
      enabled: !!resolvedAgentId,
      retry: 0,
      retryDelay: 0,
    },
  );

  return queryResult;
};
