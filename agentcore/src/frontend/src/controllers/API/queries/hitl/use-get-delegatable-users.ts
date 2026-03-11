import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface DelegatableUser {
  id: string;
  display_name: string;
  email: string | null;
}

interface GetDelegatableUsersParams {
  dept_id: string | null;
}

/**
 * Hook to fetch users in a department who can receive delegated HITL requests.
 *
 * GET /api/v1/hitl/delegatable-users?dept_id=...
 *
 * Only enabled when dept_id is provided.
 */
export const useGetDelegatableUsers: useQueryFunctionType<
  GetDelegatableUsersParams,
  DelegatableUser[]
> = (params, options?) => {
  const { query } = UseRequestProcessor();

  const getDelegatableUsersFn = async (): Promise<DelegatableUser[]> => {
    const res = await api.get<DelegatableUser[]>(
      `${getURL("HITL")}/delegatable-users?dept_id=${params?.dept_id}`,
    );
    return res.data;
  };

  return query(
    ["useGetDelegatableUsers", params?.dept_id ?? ""],
    getDelegatableUsersFn,
    {
      enabled: !!params?.dept_id,
      ...options,
    },
  );
};
