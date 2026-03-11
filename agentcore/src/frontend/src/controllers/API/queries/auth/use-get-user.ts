import type { UseMutationResult } from "@tanstack/react-query";
import useAuthStore from "@/stores/authStore";
import type { Users, useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";
export const useGetUserData: useMutationFunctionType<undefined, any> = (
  options?,
) => {
  const { mutate } = UseRequestProcessor();

  const getUserData = async () => {
    const response = await api.get<Users>(`${getURL("USERS")}/whoami`);
    return response.data; // 🔥 no side effects
  };

  const mutation: UseMutationResult = mutate(
    ["useGetUserData"],
    getUserData,
    options,
  );

  return mutation;
};

