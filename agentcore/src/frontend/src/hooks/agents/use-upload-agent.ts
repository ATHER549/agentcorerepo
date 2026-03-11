import { createFileUpload } from "@/helpers/create-file-upload";
import { getObjectsFromFilelist } from "@/helpers/get-objects-from-filelist";
import useAgentStore from "@/stores/agentStore";
import type { AgentType } from "@/types/agent";
import { processDataFromAgent } from "@/utils/reactFlowUtils";
import useAddAgent from "./use-add-agent";

const useUploadAgent = () => {
  const addAgent = useAddAgent();
  const paste = useAgentStore((state) => state.paste);

  const getAgentsFromFiles = async ({
    files,
  }: {
    files: File[];
  }): Promise<AgentType[]> => {
    const objectList = await getObjectsFromFilelist<any>(files);
    const agents: AgentType[] = [];
    objectList.forEach((object) => {
      if (object.agents) {
        object.agents.forEach((agent: AgentType) => {
          agents.push(agent);
        });
      } else {
        agents.push(object as AgentType);
      }
    });
    return agents;
  };

  const getAgentsToUpload = async ({
    files,
  }: {
    files?: File[];
  }): Promise<AgentType[]> => {
    if (!files) {
      files = await createFileUpload();
    }
    if (!files.every((file) => file.type === "application/json")) {
      throw new Error("Invalid file type");
    }
    return await getAgentsFromFiles({
      files,
    });
  };

  const uploadAgent = async ({
    files,
    isComponent,
    position,
  }: {
    files?: File[];
    isComponent?: boolean;
    position?: { x: number; y: number };
  }): Promise<void> => {
    try {
      const agents = await getAgentsToUpload({ files });
      for (const agent of agents) {
        await processDataFromAgent(agent);
      }

      if (
        isComponent !== undefined &&
        agents.every(
          (fileData) =>
            (!fileData.is_component && isComponent === true) ||
            (fileData.is_component !== undefined &&
              fileData.is_component !== isComponent),
        )
      ) {
        throw new Error(
          "You cannot upload a component as a agent or vice versa",
        );
      } else {
        let currentPosition = position;
        for (const agent of agents) {
          if (agent.data) {
            if (currentPosition) {
              paste(agent.data, currentPosition);
              currentPosition = {
                x: currentPosition.x + 50,
                y: currentPosition.y + 50,
              };
            } else {
              await addAgent({ agent });
            }
          } else {
            throw new Error("Invalid agent data");
          }
        }
      }
    } catch (e) {
      throw e;
    }
  };

  return uploadAgent;
};

export default useUploadAgent;
