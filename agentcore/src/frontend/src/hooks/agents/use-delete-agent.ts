import { useDeleteDeleteAgents } from "@/controllers/API/queries/agents/use-delete-delete-agents";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useTypesStore } from "@/stores/typesStore";
import {
  extractFieldsFromComponenents,
  processAgents,
} from "@/utils/reactFlowUtils";

const useDeleteAgent = () => {
  const setAgents = useAgentsManagerStore((state) => state.setAgents);

  const { mutate, isPending } = useDeleteDeleteAgents();

  const deleteAgent = async ({
    id,
  }: {
    id: string | string[];
  }): Promise<void> => {
    const agents = useAgentsManagerStore.getState().agents;
    return new Promise<void>((resolve, reject) => {
      if (!Array.isArray(id)) {
        id = [id];
      }
      mutate(
        { agent_ids: id },
        {
          onSuccess: () => {
            const { data, agents: myAgents } = processAgents(
              (agents ?? []).filter((agent) => !id.includes(agent.id)),
            );
            setAgents(myAgents);
            useTypesStore.setState((state) => ({
              data: { ...state.data, ["saved_components"]: data },
              ComponentFields: extractFieldsFromComponenents({
                ...state.data,
                ["saved_components"]: data,
              }),
            }));

            resolve();
          },
          onError: (e) => reject(e),
        },
      );
    });
  };

  return { deleteAgent, isDeleting: isPending };
};

export default useDeleteAgent;
