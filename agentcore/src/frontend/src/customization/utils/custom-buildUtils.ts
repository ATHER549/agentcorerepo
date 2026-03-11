import { BASE_URL_API } from "@/constants/constants";

export const customBuildUrl = (agentId: string, playgroundPage?: boolean) => {
  return `${BASE_URL_API}${playgroundPage ? "build_public_tmp" : "build"}/${agentId}/agent`;
};

export const customCancelBuildUrl = (jobId: string) => {
  return `${BASE_URL_API}build/${jobId}/cancel`;
};

export const customEventsUrl = (jobId: string) => {
  return `${BASE_URL_API}build/${jobId}/events`;
};
