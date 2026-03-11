import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface VectorDBInfo {
  id: string;
  name: string;
  description: string;
  provider: string;
  deployment: string;
  dimensions: string;
  indexType: string;
  status: string;
  vectorCount: string;
  isCustom: boolean;
  org_id?: string | null;
  dept_id?: string | null;
}

export const useGetVectorDBCatalogue: useQueryFunctionType<
  undefined,
  VectorDBInfo[]
> = (options?) => {
  const { query } = UseRequestProcessor();

  const getVectorDBCatalogueFn = async (): Promise<VectorDBInfo[]> => {
    const res = await api.get(`${getURL("VECTOR_DB_CATALOGUE")}/`);
    return res.data ?? [];
  };

  const queryResult: UseQueryResult<VectorDBInfo[], any> = query(
    ["useGetVectorDBCatalogue"],
    getVectorDBCatalogueFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
