import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { KBVisibility } from "./use-get-knowledge-bases";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface UpdateKBVisibilityParams {
  kb_id: string;
}

interface UpdateKBVisibilityPayload {
  visibility: KBVisibility;
  public_scope?: "organization" | "department";
  org_id?: string;
  dept_id?: string;
}

export const useUpdateKBVisibility: useMutationFunctionType<
  UpdateKBVisibilityParams,
  UpdateKBVisibilityPayload
> = (params, options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const updateVisibilityFn = async (
    payload: UpdateKBVisibilityPayload,
  ): Promise<any> => {
    const response = await api.patch(
      `${getURL("KNOWLEDGE_BASES")}/${params.kb_id}`,
      payload,
    );
    return response.data;
  };

  const mutation: UseMutationResult<any, any, UpdateKBVisibilityPayload> =
    mutate(["useUpdateKBVisibility"], updateVisibilityFn, {
      onSettled: (data, error, variables, context) => {
        queryClient.invalidateQueries({
          queryKey: ["useGetKnowledgeBases"],
        });
        options?.onSettled?.(data, error, variables, context);
      },
      ...options,
    });

  return mutation;
};
