import type { AgentType } from "@/types/agent";
import { processAgents } from "@/utils/reactFlowUtils";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface RegistryPreviewResponse {
  registry_id: string;
  title: string;
  deployment_env: "UAT" | "PROD" | string;
  version_number?: string | null;
  snapshot: AgentType["data"];
}

interface GetRegistryPreviewParams {
  registry_id: string;
}

export const useGetRegistryPreview: useQueryFunctionType<
  GetRegistryPreviewParams,
  AgentType | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getRegistryPreviewFn = async (): Promise<AgentType | null> => {
    if (!params?.registry_id) return null;

    const res = await api.get<RegistryPreviewResponse>(
      `${getURL("REGISTRY")}/${params.registry_id}/preview`,
    );

    const previewAgent: AgentType = {
      id: `registry-preview-${res.data.registry_id}`,
      name: res.data.title,
      description: "",
      data: res.data.snapshot,
      public: true,
      locked: true,
    };

    const { agents } = processAgents([previewAgent]);
    return agents[0];
  };

  return query(
    ["useGetRegistryPreview", params?.registry_id],
    getRegistryPreviewFn,
    {
      enabled: !!params?.registry_id,
      ...options,
    },
  );
};
