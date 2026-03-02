import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type RoleDeletePayload = {
  role_id: string;
};

export const useDeleteRole: useMutationFunctionType<RoleDeletePayload, RoleDeletePayload> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function deleteRole(payload: RoleDeletePayload): Promise<{ detail: string }> {
    const res = await api.delete(`${getURL("ROLES")}/${payload.role_id}`);
    return res.data;
  }

  const mutation: UseMutationResult<RoleDeletePayload, any, RoleDeletePayload> =
    mutate(["useDeleteRole"], deleteRole, options);

  return mutation;
};
