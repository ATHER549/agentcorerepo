import type { AgentType } from "@/types/agent";
import { downloadAgent, processAgents } from "@/utils/reactFlowUtils";
import type { useMutationFunctionType } from "../../../../types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface DownloadAgentsQueryParams {
  ids: string[];
}

export const useGetDownloadAgents: useMutationFunctionType<
  undefined,
  DownloadAgentsQueryParams
> = (options) => {
  const { mutate } = UseRequestProcessor();

  const getDownloadAgentsFn = async (params) => {
    if (!params) return;
    // need to use fetch because axios convert blob data to string, and this convertion can corrupt the file
    let response;
    if (params.ids.length === 1) {
      response = await api.get<AgentType>(`${getURL("AGENTS")}/${params.ids[0]}`);

      const agentsArrayToProcess = [response.data];
      const { agents } = processAgents(agentsArrayToProcess);

      const agent = agents[0];
      if (agent) {
        downloadAgent(agent, agent.name, agent.description);
      }
    } else {
      response = await fetch(`${getURL("AGENTS", { mode: "download/" })}`, {
        method: "POST",
        body: JSON.stringify(params.ids),
        headers: {
          "Content-Type": "application/json",
          Accept: "application/x-zip-compressed",
        },
      });
      if (!response.ok) {
        throw new Error(`Failed to download agents: ${response.statusText}`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);

      // Get the filename from the Content-Disposition header
      const contentDisposition = response.headers.get("Content-Disposition");
      let filename = "agents.zip";
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename=(.+)/);
        if (filenameMatch && filenameMatch[1]) {
          filename = filenameMatch[1].replace(/["']/g, "");
        }
      }

      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      URL.revokeObjectURL(url);
      return {};
    }
  };

  const queryResult = mutate(
    ["useGetDownloadAgentsV2"],
    getDownloadAgentsFn,
    options,
  );

  return queryResult;
};
