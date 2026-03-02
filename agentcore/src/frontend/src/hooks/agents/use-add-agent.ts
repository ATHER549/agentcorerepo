import { cloneDeep } from "lodash";
import { useParams } from "react-router-dom";
import { UUID_PARSING_ERROR } from "@/constants/constants";
import { usePostAddAgent } from "@/controllers/API/queries/agents/use-post-add-agent";
import useAlertStore from "@/stores/alertStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useFolderStore } from "@/stores/foldersStore";
import { useGlobalVariablesStore } from "@/stores/globalVariablesStore/globalVariables";
import { useTypesStore } from "@/stores/typesStore";
import type { AgentType } from "@/types/agent";
import {
  addVersionToDuplicates,
  createNewAgent,
  extractFieldsFromComponenents,
  processDataFromAgent,
  processAgents,
  updateGroupRecursion,
} from "@/utils/reactFlowUtils";
import useDeleteAgent from "./use-delete-agent";

const FLOW_CREATION_ERROR = "agent creation error";
const FOLDER_NOT_FOUND_ERROR = "Folder not found. Redirecting to agents...";
const PROJECT_CREATION_REQUIRED_SIGNAL = "__PROJECT_CREATION_REQUIRED__";
const FLOW_CREATION_ERROR_MESSAGE =
  "An unexpected error occurred, please try again";
const REDIRECT_DELAY = 3000;
const useAddAgent = () => {
  const agents = useAgentsManagerStore((state) => state.agents);
  const setAgents = useAgentsManagerStore((state) => state.setAgents);
  const { deleteAgent } = useDeleteAgent();

  const setNoticeData = useAlertStore.getState().setNoticeData;
  const { folderId } = useParams();
  const myCollectionId = useFolderStore((state) => state.myCollectionId);
  const folders = useFolderStore((state) => state.folders);

  const unavailableFields = useGlobalVariablesStore(
    (state) => state.unavailableFields,
  );
  const globalVariablesEntries = useGlobalVariablesStore(
    (state) => state.globalVariablesEntries,
  );

  const { mutate: postAddAgent } = usePostAddAgent();

  const ensureProjectId = async (selectedProjectId: string): Promise<string> => {
    const isSelectedProjectValid =
      Boolean(selectedProjectId) &&
      Boolean(folders?.some((folder) => folder.id === selectedProjectId));

    if (isSelectedProjectValid) {
      return selectedProjectId;
    }

    if (window.location.pathname.startsWith("/agents")) {
      window.dispatchEvent(new CustomEvent("open-create-project-modal"));
    } else {
      window.location.href = "/agents?openCreateProject=1";
    }

    throw new Error(PROJECT_CREATION_REQUIRED_SIGNAL);
  };

  const addAgent = async (params?: {
    agent?: AgentType;
    override?: boolean;
    new_blank?: boolean;
    projectId?: string;
  }) => {
    return new Promise(async (resolve, reject) => {
      const agent = cloneDeep(params?.agent) ?? undefined;
      const agentData = agent
        ? await processDataFromAgent(agent)
        : { nodes: [], edges: [], viewport: { zoom: 1, x: 0, y: 0 } };
      agentData?.nodes.forEach((node) => {
        updateGroupRecursion(
          node,
          agentData?.edges,
          unavailableFields,
          globalVariablesEntries,
        );
      });
      // Create anew agent with a default name if no agent is provided.
      if (params?.override && agent) {
        const agentId = agents?.find((f) => f.name === agent.name);
        if (agentId) {
          await deleteAgent({ id: agentId.id });
        }
      }

      let project_id = params?.projectId ?? folderId ?? myCollectionId ?? "";
      try {
        project_id = await ensureProjectId(project_id);
      } catch (error) {
        if (
          error instanceof Error &&
          error.message === PROJECT_CREATION_REQUIRED_SIGNAL
        ) {
          reject(error);
          return;
        }
        const message =
          error instanceof Error
            ? error.message
            : "Project creation is required before creating an agent.";
        useAlertStore.getState().setErrorData({
          title: FLOW_CREATION_ERROR,
          list: [message],
        });
        reject(error);
        return;
      }
      const agentsToCheckNames = agents?.filter(
        (f) => f.project_id === project_id,
      );
      const newAgent = createNewAgent(agentData!, project_id, agent);
      const newName = addVersionToDuplicates(newAgent, agentsToCheckNames ?? []);
      newAgent.name = newName;
      newAgent.project_id = project_id;

      postAddAgent(newAgent, {
        onSuccess: (createdAgent) => {
          // Add the new agent to the list of agents.
          const { data, agents: myAgents } = processAgents([
            createdAgent,
            ...(agents ?? []),
          ]);
          setAgents(myAgents);
          useTypesStore.setState((state) => ({
            data: { ...state.data, ["saved_components"]: data },
            ComponentFields: extractFieldsFromComponenents({
              ...state.data,
              ["saved_components"]: data,
            }),
          }));

          resolve(createdAgent.id);
        },
        onError: (error) => {
          if (error?.response?.data?.detail[0]?.type === UUID_PARSING_ERROR) {
            setNoticeData({
              title: FOLDER_NOT_FOUND_ERROR,
            });
            setTimeout(() => {
              window.location.href = `/agents`;
            }, REDIRECT_DELAY);

            return;
          }

          if (error.response?.data?.detail) {
            useAlertStore.getState().setErrorData({
              title: FLOW_CREATION_ERROR,
              list: [error.response?.data?.detail],
            });
          } else {
            useAlertStore.getState().setErrorData({
              title: FLOW_CREATION_ERROR,
              list: [error.message ?? FLOW_CREATION_ERROR_MESSAGE],
            });
          }
          reject(error); // Re-throw the error so the caller can handle it if needed},
        },
      });
    });
  };

  return addAgent;
};

export default useAddAgent;
