import type { UseMutationResult } from "@tanstack/react-query";
import type { Permission, useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useGetPermissions: useMutationFunctionType<undefined, undefined> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function getPermissions(): Promise<Permission[]> {
    const res = await api.get(`${getURL("ROLES")}/permissions`);
    if (res.status === 200) {
      return res.data;
    }
    return [];
  }

  const mutation: UseMutationResult<undefined, any, undefined> = mutate(
    ["useGetPermissions"],
    getPermissions,
    options,
  );

  return mutation;
};
