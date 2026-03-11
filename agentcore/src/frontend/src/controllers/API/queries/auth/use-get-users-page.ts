import type { UseMutationResult } from "@tanstack/react-query";
import type { Users, useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface getUsersQueryParams {
  skip: number;
  limit: number;
  role?: string;
  q?: string;
}

export const useGetUsers: useMutationFunctionType<any, getUsersQueryParams> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  async function getUsers({
    skip,
    limit,
    role,
    q,
  }: getUsersQueryParams): Promise<Array<Users>> {
    const roleParam = role ? `&role=${encodeURIComponent(role)}` : "";
    const qParam = q ? `&q=${encodeURIComponent(q)}` : "";
    const res = await api.get(
      `${getURL("USERS")}/?skip=${skip}&limit=${limit}${roleParam}${qParam}`,
    );
    if (res.status === 200) {
      return res.data;
    }
    return [];
  }

  const mutation: UseMutationResult<
    getUsersQueryParams,
    any,
    getUsersQueryParams
  > = mutate(["useGetUsers"], getUsers, options);

  return mutation;
};
