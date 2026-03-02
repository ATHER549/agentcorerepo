import type { UseMutationResult } from "@tanstack/react-query";
import { useFolderStore } from "@/stores/foldersStore";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface DeleteFoldersParams {
  project_id: string;
}

export const useDeleteFolders: useMutationFunctionType<
  undefined,
  DeleteFoldersParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();
  const setFolders = useFolderStore((state) => state.setFolders);
  const folders = useFolderStore((state) => state.folders);

  const deleteFolder = async ({
    project_id,
  }: DeleteFoldersParams): Promise<any> => {
    await api.delete(`${getURL("PROJECTS")}/${project_id}`);
    setFolders(folders.filter((f) => f.id !== project_id));
    return project_id;
  };

  const mutation: UseMutationResult<
    DeleteFoldersParams,
    any,
    DeleteFoldersParams
  > = mutate(["useDeleteFolders"], deleteFolder, {
    ...options,
    onSettled: (id) => {
      queryClient.refetchQueries({ queryKey: ["useGetFolders", id] });
    },
  });

  return mutation;
};
