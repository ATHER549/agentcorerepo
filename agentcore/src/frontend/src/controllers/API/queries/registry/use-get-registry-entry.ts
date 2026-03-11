import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface RegistryEntryDetail {
  id: string;
  org_id?: string | null;
  agent_id: string;
  agent_deployment_id: string;
  deployment_env: "UAT" | "PROD" | string;
  title: string;
  summary?: string | null;
  tags?: string[] | null;
  rating?: number | null;
  rating_count: number;
  visibility: "PUBLIC" | "PRIVATE" | string;
  listed_by: string;
  listed_by_username?: string | null;
  listed_at: string;
  created_at: string;
  updated_at: string;
  version_number?: string | null;
  agent_description?: string | null;
  publish_description?: string | null;
  deployed_by?: string | null;
  deployed_by_username?: string | null;
  deployed_at?: string | null;
}

interface GetRegistryEntryParams {
  registry_id: string;
}

export const useGetRegistryEntry: useQueryFunctionType<
  GetRegistryEntryParams,
  RegistryEntryDetail | null
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getRegistryEntryFn = async (): Promise<RegistryEntryDetail | null> => {
    if (!params?.registry_id) return null;
    const res = await api.get<RegistryEntryDetail>(
      `${getURL("REGISTRY")}/${params.registry_id}`,
    );
    return res.data;
  };

  return query(
    ["useGetRegistryEntry", params?.registry_id],
    getRegistryEntryFn,
    {
      enabled: !!params?.registry_id,
      ...options,
    },
  );
};

