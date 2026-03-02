import type { UseMutationResult } from "@tanstack/react-query";
import type { Role, useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type RolePermissionsPayload = {
  role_id: string;
  permissions: string[];
};

export const usePutRolePermissions: useMutationFunctionType<RolePermissionsPayload, RolePermissionsPayload> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function putRolePermissions(payload: RolePermissionsPayload): Promise<Role> {
    const res = await api.put(
      `${getURL("ROLES")}/${payload.role_id}/permissions`,
      payload.permissions,
    );
    return res.data;
  }

  const mutation: UseMutationResult<RolePermissionsPayload, any, RolePermissionsPayload> =
    mutate(["usePutRolePermissions"], putRolePermissions, options);

  return mutation;
};
