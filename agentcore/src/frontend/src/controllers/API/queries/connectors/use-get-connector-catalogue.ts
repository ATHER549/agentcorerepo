import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface ConnectorInfo {
  id: string;
  name: string;
  description: string;
  provider: string;
  host: string | null;
  port: number | null;
  database_name: string | null;
  schema_name: string | null;
  username: string | null;
  ssl_enabled: boolean;
  provider_config?: Record<string, any> | null;
  status: "connected" | "disconnected" | "error";
  tables_metadata: any[] | null;
  last_tested_at: string | null;
  isCustom: boolean;
  org_id?: string | null;
  dept_id?: string | null;
  visibility?: "private" | "public";
  public_scope?: "organization" | "department" | null;
  public_dept_ids?: string[];
  shared_user_ids?: string[];
}

export const useGetConnectorCatalogue: useQueryFunctionType<
  undefined,
  ConnectorInfo[]
> = (options?) => {
  const { query } = UseRequestProcessor();

  const getConnectorCatalogueFn = async (): Promise<ConnectorInfo[]> => {
    const res = await api.get(`${getURL("CONNECTOR_CATALOGUE")}/`);
    return res.data ?? [];
  };

  const queryResult: UseQueryResult<ConnectorInfo[], any> = query(
    ["useGetConnectorCatalogue"],
    getConnectorCatalogueFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
