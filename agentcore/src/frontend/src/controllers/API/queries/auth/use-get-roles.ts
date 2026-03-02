import type { UseMutationResult } from "@tanstack/react-query";
import type { Role, useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useGetRoles: useMutationFunctionType<undefined, undefined> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function getRoles(): Promise<Role[]> {
    const res = await api.get(`${getURL("ROLES")}/`);
    if (res.status === 200) {
      return res.data;
    }
    return [];
  }

  const mutation: UseMutationResult<undefined, any, undefined> = mutate(
    ["useGetRoles"],
    getRoles,
    options,
  );

  return mutation;
};
