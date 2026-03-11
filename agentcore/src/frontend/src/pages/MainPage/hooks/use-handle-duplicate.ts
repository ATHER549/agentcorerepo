import { useParams } from "react-router-dom";
import { usePostAddAgent } from "@/controllers/API/queries/agents/use-post-add-agent";
import { useFolderStore } from "@/stores/foldersStore";
import type { AgentType } from "@/types/agent";
import { createNewAgent } from "@/utils/reactFlowUtils";

type UseDuplicateAgentsParams = {
  agent?: AgentType;
};

const useDuplicateAgent = ({ agent }: UseDuplicateAgentsParams) => {
  const { mutateAsync: postAddAgent } = usePostAddAgent();
  const { folderId } = useParams();
  const myCollectionId = useFolderStore((state) => state.myCollectionId);

  const handleDuplicate = async () => {
    if (agent?.data) {
      const project_id = folderId ?? myCollectionId ?? "";

      const newAgent = createNewAgent(agent.data, project_id, agent);

      newAgent.project_id = project_id;

      await postAddAgent(newAgent);
    }
  };

  return { handleDuplicate };
};

export default useDuplicateAgent;
