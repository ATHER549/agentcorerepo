import type { FileType } from "@/types/file_management";
import type { useQueryFunctionType } from "../../../../types/api";
import useAuthStore from "@/stores/authStore";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type FilesResponse = FileType[];

export const useGetFilesV2: useQueryFunctionType<undefined, FilesResponse> = (
  config,
) => {
  const { query } = UseRequestProcessor();
  const userId = useAuthStore((state) => state.userData?.id);

  const getFilesFn = async () => {
    const response = await api.get<FilesResponse>(
      `${getURL("FILE_MANAGEMENT", {}, true)}`,
    );
    return response["data"] ?? [];
  };

  const queryResult = query(["useGetFilesV2", userId ?? "anonymous"], getFilesFn, {
    ...config,
  });

  return queryResult;
};
