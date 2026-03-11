import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IDeleteAgents {
  agent_ids: string[];
}

export const useDeleteDeleteAgents: useMutationFunctionType<
  undefined,
  IDeleteAgents
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const deleteAgentsFn = async (payload: IDeleteAgents): Promise<any> => {
    const response = await api.delete<any>(`${getURL("AGENTS")}/`, {
      data: payload.agent_ids,
    });

    return response.data;
  };

  const mutation: UseMutationResult<IDeleteAgents, any, IDeleteAgents> = mutate(
    ["useLoginUser"],
    deleteAgentsFn,
    {
      ...options,
      onSettled: () => {
        queryClient.refetchQueries({ queryKey: ["useGetFolder"] });
      },
    },
  );

  return mutation;
};
