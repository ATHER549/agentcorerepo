import type { UseMutationResult } from "@tanstack/react-query";
import type { Role, useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type RoleCreatePayload = {
  name: string;
  description?: string | null;
  permissions: string[];
};

export const usePostRole: useMutationFunctionType<RoleCreatePayload, RoleCreatePayload> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function createRole(payload: RoleCreatePayload): Promise<Role> {
    const res = await api.post(getURL("ROLES"), payload);
    return res.data;
  }

  const mutation: UseMutationResult<RoleCreatePayload, any, RoleCreatePayload> =
    mutate(["usePostRole"], createRole, options);

  return mutation;
};
