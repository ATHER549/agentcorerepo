import type { reactFlowJsonObject } from "@xyflow/react";
import { useGetAgent } from "@/controllers/API/queries/agents/use-get-agent";
import { usePatchUpdateAgent } from "@/controllers/API/queries/agents/use-patch-update-agent";
import useAlertStore from "@/stores/alertStore";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import type { AllNodeType, EdgeType, AgentType } from "@/types/agent";
import { customStringify } from "@/utils/reactFlowUtils";

const useSaveAgent = () => {
  const setAgents = useAgentsManagerStore((state) => state.setAgents);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSaveLoading = useAgentsManagerStore((state) => state.setSaveLoading);
  const setCurrentAgent = useAgentStore((state) => state.setCurrentAgent);

  const { mutate: getAgent } = useGetAgent();
  const { mutate } = usePatchUpdateAgent();

  const saveAgent = async (agent?: AgentType): Promise<void> => {
    const currentAgent = useAgentStore.getState().currentAgent;
    const currentSavedAgent = useAgentsManagerStore.getState().currentAgent;
    if (
      customStringify(agent || currentAgent) !== customStringify(currentSavedAgent)
    ) {
      setSaveLoading(true);

      const agentData = currentAgent?.data;
      const nodes = useAgentStore.getState().nodes;
      const edges = useAgentStore.getState().edges;
      const reactFlowInstance = useAgentStore.getState().reactFlowInstance;

      return new Promise<void>((resolve, reject) => {
        if (currentAgent) {
          agent = agent || {
            ...currentAgent,
            data: {
              ...agentData,
              nodes,
              edges,
              viewport: reactFlowInstance?.getViewport() ?? {
                zoom: 1,
                x: 0,
                y: 0,
              },
            },
          };
        }

        if (agent) {
          if (!agent?.data) {
            getAgent(
              { id: agent!.id },
              {
                onSuccess: (agentResponse) => {
                  agent!.data = agentResponse.data as reactFlowJsonObject<
                    AllNodeType,
                    EdgeType
                  >;
                },
              },
            );
          }

          const {
            id,
            name,
            data,
            description,
            project_id,
            endpoint_name,
            locked,
          } = agent;
          if (!currentSavedAgent?.data?.nodes.length || data!.nodes.length > 0) {
            mutate(
              {
                id,
                name,
                data: data!,
                description,
                project_id,
                endpoint_name,
                locked,
              },
              {
                onSuccess: (updatedAgent) => {
                  const agents = useAgentsManagerStore.getState().agents;
                  setSaveLoading(false);
                  const agentList = Array.isArray(agents) ? agents : [];
                  const hasExisting = agentList.some(
                    (existingAgent) => existingAgent.id === updatedAgent.id,
                  );
                  const nextAgents = hasExisting
                    ? agentList.map((existingAgent) =>
                        existingAgent.id === updatedAgent.id
                          ? updatedAgent
                          : existingAgent,
                      )
                    : [updatedAgent, ...agentList];
                  setAgents(nextAgents);
                  setCurrentAgent(updatedAgent);
                  resolve();
                },
                onError: (e) => {
                  setErrorData({
                    title: "Failed to save agent",
                    list: [e.message],
                  });
                  setSaveLoading(false);
                  reject(e);
                },
              },
            );
          } else {
            setSaveLoading(false);
          }
        } else {
          setErrorData({
            title: "Failed to save agent",
            list: ["agent not found"],
          });
          reject(new Error("agent not found"));
        }
      });
    }
  };

  return saveAgent;
};

export default useSaveAgent;
