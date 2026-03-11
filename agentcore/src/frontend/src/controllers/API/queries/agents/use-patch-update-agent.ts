import type { UseMutationResult } from "@tanstack/react-query";
import type { reactFlowJsonObject } from "@xyflow/react";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IPatchUpdateAgent {
  id: string;
  name?: string;
  data?: reactFlowJsonObject;
  description?: string;
  project_id?: string | null | undefined;
  endpoint_name?: string | null | undefined;
  locked?: boolean | null | undefined;
  access_type?: "PUBLIC" | "PRIVATE" | "PROTECTED";
}

export const usePatchUpdateAgent: useMutationFunctionType<
  undefined,
  IPatchUpdateAgent
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const PatchUpdateAgentFn = async ({
    id,
    ...payload
  }: IPatchUpdateAgent): Promise<any> => {
    const response = await api.patch(`${getURL("AGENTS")}/${id}`, payload);

    return response.data;
  };

  const mutation: UseMutationResult<IPatchUpdateAgent, any, IPatchUpdateAgent> =
    mutate(["usePatchUpdateAgent"], PatchUpdateAgentFn, {
      onSettled: (res) => {
        queryClient.refetchQueries({
          queryKey: ["useGetFolders", res.project_id],
        }),
          queryClient.refetchQueries({
            queryKey: ["useGetFolder"],
          });
      },
      ...options,
    });

  return mutation;
};
