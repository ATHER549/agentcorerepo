import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IDeleteBuilds {
  agentId: string;
}

// add types for error handling and success
export const useDeleteBuilds: useMutationFunctionType<
  undefined,
  IDeleteBuilds
> = (options) => {
  const { mutate } = UseRequestProcessor();

  const deleteBuildsFn = async (payload: IDeleteBuilds): Promise<any> => {
    const config = {};
    config["params"] = { agent_id: payload.agentId };
    const res = await api.delete<any>(`${getURL("BUILDS")}`, config);
    return res.data;
  };

  const mutation = mutate(["useDeleteBuilds"], deleteBuildsFn, options);

  return mutation;
};
