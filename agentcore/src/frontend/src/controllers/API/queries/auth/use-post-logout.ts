import { Cookies } from "react-cookie";
import {
} from "@/constants/constants";
import useAuthStore from "@/stores/authStore";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useFolderStore } from "@/stores/foldersStore";
import type { useMutationFunctionType } from "@/types/api";
import { getAuthCookie } from "@/utils/utils";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useLogout: useMutationFunctionType<undefined, void> = (
  options?,
) => {
  const { mutate, queryClient } = UseRequestProcessor();
  const cookies = new Cookies();
  const logout = useAuthStore((state) => state.logout);

  async function logoutUser(): Promise<any> {

    const res = await api.post(`${getURL("LOGOUT")}`);
    return res.data;
  }

  const mutation = mutate(["useLogout"], logoutUser, {
    onSuccess: () => {
      logout();
      queryClient.clear();

      useAgentStore.getState().resetAgentState();
      useAgentsManagerStore.getState().resetStore();
      useFolderStore.getState().resetStore();

      queryClient.invalidateQueries({ queryKey: ["useGetRefreshAgentsQuery"] });
      queryClient.invalidateQueries({ queryKey: ["useGetFolders"] });
      queryClient.invalidateQueries({ queryKey: ["useGetFolder"] });
    },
    onError: (error) => {
      console.error(error);
    },
    ...options,
  });

  return mutation;
};
