import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface CloneRegistryRequest {
  registry_id: string;
  project_id: string;
  new_name?: string;
}

interface CloneRegistryResponse {
  agent_id: string;
  agent_name: string;
  project_id: string;
  cloned_from_registry_id: string;
  cloned_from_deployment_id: string;
  environment_source: "uat" | "prod" | string;
}

export const usePostRegistryClone: useMutationFunctionType<
  undefined,
  CloneRegistryRequest,
  CloneRegistryResponse
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const cloneRegistryFn = async (
    params: CloneRegistryRequest,
  ): Promise<CloneRegistryResponse> => {
    const res = await api.post<CloneRegistryResponse>(
      `${getURL("REGISTRY")}/${params.registry_id}/clone`,
      {
        project_id: params.project_id,
        new_name: params.new_name || undefined,
      },
    );
    return res.data;
  };

  return mutate(["usePostRegistryClone"], cloneRegistryFn, {
    ...options,
    onSuccess: (data, variables, context) => {
      queryClient.invalidateQueries({ queryKey: ["useGetFolders"] });
      options?.onSuccess?.(data, variables, context);
    },
  });
};

