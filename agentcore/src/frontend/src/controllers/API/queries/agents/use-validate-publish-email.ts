import type { UseMutationResult } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface IValidatePublishEmailRequest {
  agent_id: string;
  email: string;
}

export interface IValidatePublishEmailResponse {
  agent_id: string;
  email: string;
  department_id: string | null;
  exists_in_department: boolean;
  message: string;
}

export const useValidatePublishEmail = (options?: any) => {
  const { mutate } = UseRequestProcessor();

  const validatePublishEmailFn = async (
    payload: IValidatePublishEmailRequest,
  ): Promise<IValidatePublishEmailResponse> => {
    const response = await api.get<IValidatePublishEmailResponse>(
      `${getURL("PUBLISH")}/validate-email`,
      {
        params: {
          agent_id: payload.agent_id,
          email: payload.email,
        },
      },
    );
    return response.data;
  };

  const mutation = mutate(["useValidatePublishEmail"], validatePublishEmailFn, options) as UseMutationResult<
    IValidatePublishEmailResponse,
    any,
    IValidatePublishEmailRequest
  >;

  return mutation;
};
