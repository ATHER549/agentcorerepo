import { AGENTCORE_ACCESS_TOKEN } from "@/constants/constants";
import useAuthStore from "@/stores/authStore";
import type { useMutationFunctionType } from "@/types/api";
import { setLocalStorage } from "@/utils/local-storage-util";
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
    // Cookies are owned by backend Set-Cookie headers.
    // Avoid client-side cookie rewrites that can break Secure/SameSite behavior.
    setLocalStorage(AGENTCORE_ACCESS_TOKEN, res.data.access_token);
    useAuthStore.getState().setAccessToken(res.data.access_token);

    return res.data;
  }

const mutation = mutate(["useRefreshAccessToken"], refreshAccess, {
  ...options,
  retry: 2, // normal retry for transient network errors
});
  return mutation;
};
