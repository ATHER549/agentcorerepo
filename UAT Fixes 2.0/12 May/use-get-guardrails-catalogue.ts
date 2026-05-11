import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface GuardrailRuntimeConfig {
  config_yml?: string;
  rails_co?: string;
  prompts_yml?: string;
  files?: Record<string, string>;
}

export type GuardrailEnvironment = "uat" | "prod";

export interface GuardrailInfo {
  id: string;
  name: string;
  description: string;
  framework?: "nemo" | "arize";
  provider: string;
  modelRegistryId?: string | null;
  modelName?: string | null;
  modelDisplayName?: string | null;
  category: string;
  status: "active" | "inactive";
  rulesCount?: number;
  isCustom: boolean;
  runtimeConfig?: GuardrailRuntimeConfig | null;
  runtimeReady?: boolean;
  org_id?: string | null;
  dept_id?: string | null;
  visibility?: "private" | "public";
  public_scope?: "organization" | "department" | null;
  public_dept_ids?: string[];
  created_by?: string | null;
  created_by_email?: string | null;
  created_by_id?: string | null;
  // Versioning
  latestVersion?: number;
}

export interface GuardrailCreateOrUpdatePayload {
  name: string;
  description?: string | null;
  framework?: "nemo" | "arize";
  modelRegistryId: string;
  category: string;
  status: "active" | "inactive";
  rulesCount?: number;
  isCustom: boolean;
  runtimeConfig?: GuardrailRuntimeConfig | null;
  org_id?: string | null;
  dept_id?: string | null;
  visibility?: "private" | "public";
  public_scope?: "organization" | "department" | null;
  public_dept_ids?: string[] | null;
}

export interface GuardrailsCatalogueParams {
  framework?: "nemo" | "arize";
  environment?: GuardrailEnvironment;
}

export const useGetGuardrailsCatalogue: useQueryFunctionType<
  GuardrailsCatalogueParams,
  GuardrailInfo[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getGuardrailsCatalogueFn = async (): Promise<GuardrailInfo[]> => {
    const queryParams: Record<string, string> = {};
    if (params?.framework) queryParams.framework = params.framework;
    if (params?.environment) queryParams.environment = params.environment;

    const res = await api.get(`${getURL("GUARDRAILS_CATALOGUE")}/`, {
      params: Object.keys(queryParams).length > 0 ? queryParams : undefined,
    });
    return res.data ?? [];
  };

  const queryResult: UseQueryResult<GuardrailInfo[], any> = query(
    [
      "useGetGuardrailsCatalogue",
      params?.framework ?? "all",
      params?.environment ?? "uat",
    ],
    getGuardrailsCatalogueFn,
    {
      refetchOnMount: true,
      ...options,
    },
  );

  return queryResult;
};
