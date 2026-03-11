import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";

export const useDeleteMCPServer = () => {
  const queryClient = useQueryClient();

  return useMutation<void, Error, { id: string }>({
    mutationFn: async ({ id }) => {
      await api.delete(`api/mcp/registry/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-registry"] });
    },
  });
};
