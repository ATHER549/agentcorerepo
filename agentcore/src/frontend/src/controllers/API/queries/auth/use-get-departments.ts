import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type DepartmentListItem = {
  id: string;
  name: string;
  org_id: string;
};

export const useGetDepartments: useMutationFunctionType<
  DepartmentListItem[],
  undefined
> = (options?) => {
  const { mutate } = UseRequestProcessor();

  async function getDepartments(): Promise<DepartmentListItem[]> {
    const res = await api.get(`${getURL("USERS")}/departments`);
    if (res.status === 200) {
      return res.data ?? [];
    }
    return [];
  }

  const mutation: UseMutationResult<DepartmentListItem[], any, undefined> = mutate(
    ["useGetDepartments"],
    getDepartments,
    options,
  );

  return mutation;
};

