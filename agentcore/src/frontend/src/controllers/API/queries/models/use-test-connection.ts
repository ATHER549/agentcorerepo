import { useMutation } from "@tanstack/react-query";
import { api } from "../../api";
import type {
  TestConnectionRequest,
  TestConnectionResponse,
} from "@/types/models/models";

export const useTestModelConnection = () => {
  return useMutation<
    TestConnectionResponse,
    Error,
    TestConnectionRequest & { isEmbedding?: boolean }
  >({
    mutationFn: async ({ isEmbedding, ...data }) => {
      const endpoint = isEmbedding
        ? "api/models/registry/test-embedding-connection"
        : "api/models/registry/test-connection";
      const response = await api.post(endpoint, data);
      return response.data;
    },
  });
};
