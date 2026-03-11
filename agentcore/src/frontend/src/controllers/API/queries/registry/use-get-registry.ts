import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface RegistryEntry {
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
  listed_by_email?: string | null;
  listed_at: string;
  created_at: string;
  updated_at: string;
}

export interface RegistryListResponse {
  items: RegistryEntry[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

interface GetRegistryParams {
  search?: string;
  page?: number;
  page_size?: number;
  deployment_env?: "UAT" | "PROD";
}

export const useGetRegistry: useQueryFunctionType<
  GetRegistryParams,
  RegistryListResponse
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getRegistryFn = async (): Promise<RegistryListResponse> => {
    const res = await api.get<RegistryListResponse>(`${getURL("REGISTRY")}`, {
      params: {
        search: params?.search || undefined,
        page: params?.page ?? 1,
        page_size: params?.page_size ?? 20,
        deployment_env: params?.deployment_env || undefined,
      },
    });
    return res.data;
  };

  return query(
    [
      "useGetRegistry",
      params?.search,
      params?.page,
      params?.page_size,
      params?.deployment_env,
    ],
    getRegistryFn,
    options,
  );
};
