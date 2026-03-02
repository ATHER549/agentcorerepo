import { Cookies } from "react-cookie";
import {  AGENTCORE_REFRESH_TOKEN } from "@/constants/constants";
import useAuthStore from "@/stores/authStore";
import type { useMutationFunctionType } from "@/types/api";
import { setAuthCookie } from "@/utils/utils";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IRefreshAccessToken {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export const useRefreshAccessToken: useMutationFunctionType<
  undefined,
  undefined | void,
  IRefreshAccessToken
> = (options?) => {
  const { mutate } = UseRequestProcessor();

  async function refreshAccess(): Promise<IRefreshAccessToken> {
    const res = await api.post<IRefreshAccessToken>(`${getURL("REFRESH")}`);
    const cookies = new Cookies();
    setAuthCookie(cookies, AGENTCORE_REFRESH_TOKEN, res.data.refresh_token);

    return res.data;
  }

const mutation = mutate(["useRefreshAccessToken"], refreshAccess, {
  ...options,
  retry: 2, // normal retry for transient network errors
});
  return mutation;
};
