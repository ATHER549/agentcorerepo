import type { AgentType } from "@/types/agent";

export const customDownloadAgent = (
  agent: AgentType,
  sortedJsonString: string,
  agentName: string,
) => {
  const dataUri = `data:text/json;chatset=utf-8,${encodeURIComponent(sortedJsonString)}`;
  const downloadLink = document.createElement("a");
  downloadLink.href = dataUri;
  downloadLink.download = `${agentName || agent.name}.json`;

  downloadLink.click();
};
