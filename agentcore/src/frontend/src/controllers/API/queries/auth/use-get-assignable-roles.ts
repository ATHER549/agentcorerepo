import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useGetAssignableRoles: useMutationFunctionType<undefined, undefined> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function getAssignableRoles(): Promise<string[]> {
    const res = await api.get(`${getURL("USERS")}/assignable-roles`);
    if (res.status === 200) {
      return res.data;
    }
    return [];
  }

  const mutation: UseMutationResult<undefined, any, undefined> = mutate(
    ["useGetAssignableRoles"],
    getAssignableRoles,
    options,
  );

  return mutation;
};
