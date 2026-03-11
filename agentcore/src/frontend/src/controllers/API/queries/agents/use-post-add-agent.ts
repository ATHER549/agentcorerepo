import type { UseMutationResult } from "@tanstack/react-query";
import type { reactFlowJsonObject } from "@xyflow/react";
import { useFolderStore } from "@/stores/foldersStore";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IPostAddAgent {
  name: string;
  data: reactFlowJsonObject;
  description: string;
  is_component: boolean;
  project_id: string;
  endpoint_name: string | undefined;
  icon: string | undefined;
  gradient: string | undefined;
  tags: string[] | undefined;
}

export const usePostAddAgent: useMutationFunctionType<
  undefined,
  IPostAddAgent
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();
  const myCollectionId = useFolderStore((state) => state.myCollectionId);

  const postAddAgentFn = async (payload: IPostAddAgent): Promise<any> => {
    const response = await api.post(`${getURL("AGENTS")}/`, {
      name: payload.name,
      data: payload.data,
      description: payload.description,
      is_component: payload.is_component,
      project_id: payload.project_id || null,
      icon: payload.icon || null,
      gradient: payload.gradient || null,
      endpoint_name: payload.endpoint_name || null,
      tags: payload.tags || null,
    });
    return response.data;
  };

  const mutation: UseMutationResult<IPostAddAgent, any, IPostAddAgent> = mutate(
    ["usePostAddAgent"],
    postAddAgentFn,
    {
      ...options,
      onSettled: (response) => {
        if (response) {
          queryClient.refetchQueries({
            queryKey: [
              "useGetRefreshAgentsQuery",
              { get_all: true, header_agents: true },
            ],
          });

          queryClient.refetchQueries({
            queryKey: ["useGetFolder", response.project_id ?? myCollectionId],
          });
        }
      },
    },
  );

  return mutation;
};
