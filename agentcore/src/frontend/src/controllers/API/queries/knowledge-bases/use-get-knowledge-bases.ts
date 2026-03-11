import type { UseQueryResult } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import useAuthStore from "@/stores/authStore";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type KBVisibility = "PRIVATE" | "DEPARTMENT" | "ORGANIZATION";

export interface KnowledgeBaseInfo {
  id: string;
  name: string;
  org_id?: string | null;
  dept_id?: string | null;
  embedding_provider?: string;
  embedding_model?: string;
  size: number;
  words: number;
  characters: number;
  chunks: number;
  avg_chunk_size: number;
  file_count?: number;
  visibility?: KBVisibility;
  created_by?: string;
  updated_at?: string | null;
  last_activity?: string | null;
  is_own_kb?: boolean;
  created_by_email?: string | null;
  department_name?: string | null;
  organization_name?: string | null;
}

export const useGetKnowledgeBases: useQueryFunctionType<
  undefined,
  KnowledgeBaseInfo[]
> = (options?) => {
  const { query } = UseRequestProcessor();
  const userId = useAuthStore((state) => state.userData?.id);

  const getKnowledgeBasesFn = async (): Promise<KnowledgeBaseInfo[]> => {
    const res = await api.get(`${getURL("KNOWLEDGE_BASES")}/`);
    return res.data;
  };

  const queryResult: UseQueryResult<KnowledgeBaseInfo[], any> = query(
    ["useGetKnowledgeBases", userId ?? "anonymous"],
    getKnowledgeBasesFn,
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
