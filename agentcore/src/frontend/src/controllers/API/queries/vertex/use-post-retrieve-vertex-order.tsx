import type { Edge, Node, reactFlowJsonObject } from "@xyflow/react";
import type { AxiosRequestConfig } from "axios";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface retrieveGetVerticesOrder {
  agentId: string;
  data?: reactFlowJsonObject;
  stopNodeId?: string;
  startNodeId?: string;
}

interface retrieveGetVerticesOrderResponse {
  ids: string[];
  rund_id: string;
  vertices_to_run: string[];
}

// add types for error handling and success
export const usePostRetrieveVertexOrder: useMutationFunctionType<
  undefined,
  retrieveGetVerticesOrder,
  retrieveGetVerticesOrderResponse
> = (options) => {
  const { mutate } = UseRequestProcessor();

  const postRetrieveVertexOrder = async ({
    agentId,
    data: agent,
    startNodeId,
    stopNodeId,
  }: retrieveGetVerticesOrder): Promise<retrieveGetVerticesOrderResponse> => {
    // nodeId is optional and is a query parameter
    // if nodeId is not provided, the API will return all vertices
    const config: AxiosRequestConfig<any> = {};
    if (stopNodeId) {
      config["params"] = { stop_component_id: decodeURIComponent(stopNodeId) };
    } else if (startNodeId) {
      config["params"] = {
        start_component_id: decodeURIComponent(startNodeId),
      };
    }
    let requestBody: { nodes: Node[]; edges: Edge[] } | null = null;
    if (agent && agent.nodes && agent.edges) {
      const { nodes, edges } = agent;
      requestBody = {
        nodes,
        edges,
      };
    }
    const response = await api.post(
      `${getURL("BUILD")}/${agentId}/vertices`,
      requestBody,
      config,
    );

    return response.data;
  };

  const mutation = mutate(
    ["usePostRetrieveVertexOrder"],
    postRetrieveVertexOrder,
    {
      ...options,
      retry: 0,
      retryDelay: 0,
    },
  );

  return mutation;
};
