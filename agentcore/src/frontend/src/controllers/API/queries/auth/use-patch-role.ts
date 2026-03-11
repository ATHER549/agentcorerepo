import type { UseMutationResult } from "@tanstack/react-query";
import type { Role, useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type RolePatchPayload = {
  role_id: string;
  role: {
    name?: string | null;
    description?: string | null;
    permissions?: string[] | null;
  };
};

export const usePatchRole: useMutationFunctionType<RolePatchPayload, RolePatchPayload> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function patchRole(payload: RolePatchPayload): Promise<Role> {
    const res = await api.patch(`${getURL("ROLES")}/${payload.role_id}`, payload.role);
    return res.data;
  }

  const mutation: UseMutationResult<RolePatchPayload, any, RolePatchPayload> =
    mutate(["usePatchRole"], patchRole, options);

  return mutation;
};
