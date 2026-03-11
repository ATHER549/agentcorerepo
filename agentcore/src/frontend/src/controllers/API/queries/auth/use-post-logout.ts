import useAuthStore from "@/stores/authStore";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useFolderStore } from "@/stores/foldersStore";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useLogout: useMutationFunctionType<undefined, void> = (
  options?,
) => {
  const { mutate, queryClient } = UseRequestProcessor();
  const logout = useAuthStore((state) => state.logout);

  const clearClientAuthState = () => {
    logout();
    queryClient.clear();

    useAgentStore.getState().resetAgentState();
    useAgentsManagerStore.getState().resetStore();
    useFolderStore.getState().resetStore();

    queryClient.invalidateQueries({ queryKey: ["useGetRefreshAgentsQuery"] });
    queryClient.invalidateQueries({ queryKey: ["useGetFolders"] });
    queryClient.invalidateQueries({ queryKey: ["useGetFolder"] });
  };

  async function logoutUser(): Promise<any> {

    const res = await api.post(`${getURL("LOGOUT")}`);
    return res.data;
  }

  const mutation = mutate(["useLogout"], logoutUser, {
    onSuccess: () => {
      clearClientAuthState();
    },
    onError: (error) => {
      console.error(error);
      // If server-side logout fails (expired/invalid session), still force
      // local logout so protected routes redirect to /login.
      clearClientAuthState();
    },
    ...options,
  });

  return mutation;
};
