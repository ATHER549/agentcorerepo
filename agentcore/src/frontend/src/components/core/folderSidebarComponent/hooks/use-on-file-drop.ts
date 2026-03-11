import { usePostUploadAgentToFolder } from "@/controllers/API/queries/folders/use-post-upload-to-folder";
import useSaveAgent from "@/hooks/agents/use-save-agent";
import {
  UPLOAD_ALERT_LIST,
  WRONG_FILE_ERROR_ALERT,
} from "../../../../constants/alerts_constants";
import useAlertStore from "../../../../stores/alertStore";
import useAgentsManagerStore from "../../../../stores/agentsManagerStore";
import { useFolderStore } from "../../../../stores/foldersStore";
import { addVersionToDuplicates } from "../../../../utils/reactFlowUtils";

const useFileDrop = (folderId: string) => {
  const setFolderDragging = useFolderStore((state) => state.setFolderDragging);
  const setFolderIdDragging = useFolderStore(
    (state) => state.setFolderIdDragging,
  );

  const myCollectionId = useFolderStore((state) => state.myCollectionId);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const saveAgent = useSaveAgent();
  const agents = useAgentsManagerStore((state) => state.agents);

  const { mutate: uploadAgentToFolder } = usePostUploadAgentToFolder();
  const handleFileDrop = async (e, folderId) => {
    if (e.dataTransfer.types.some((type) => type === "Files")) {
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        const firstFile = e.dataTransfer.files[0];
        if (firstFile.type === "application/json") {
          uploadFormData(firstFile, folderId);
        } else {
          setErrorData({
            title: WRONG_FILE_ERROR_ALERT,
            list: [UPLOAD_ALERT_LIST],
          });
        }
      }
    }
  };

  const dragOver = (
    e:
      | React.DragEvent<HTMLDivElement>
      | React.DragEvent<HTMLButtonElement>
      | React.DragEvent<HTMLAnchorElement>,
    folderId: string,
  ) => {
    e.preventDefault();

    if (e.dataTransfer.types.some((types) => types === "Files")) {
      setFolderDragging(true);
    }
    setFolderIdDragging(folderId);
  };

  const dragEnter = (
    e:
      | React.DragEvent<HTMLDivElement>
      | React.DragEvent<HTMLButtonElement>
      | React.DragEvent<HTMLAnchorElement>,
    folderId: string,
  ) => {
    if (e.dataTransfer.types.some((types) => types === "Files")) {
      setFolderDragging(true);
    }
    setFolderIdDragging(folderId);
    e.preventDefault();
  };

  const dragLeave = (
    e:
      | React.DragEvent<HTMLDivElement>
      | React.DragEvent<HTMLButtonElement>
      | React.DragEvent<HTMLAnchorElement>,
  ) => {
    e.preventDefault();
    if (e.target === e.currentTarget) {
      setFolderDragging(false);
      setFolderIdDragging("");
    }
  };

  const onDrop = (
    e:
      | React.DragEvent<HTMLDivElement>
      | React.DragEvent<HTMLButtonElement>
      | React.DragEvent<HTMLAnchorElement>,
    folderId: string,
  ) => {
    if (e?.dataTransfer?.getData("agent")) {
      const data = JSON.parse(e?.dataTransfer?.getData("agent"));

      if (data) {
        uploadFromDragCard(data.id, folderId);
        return;
      }
    }

    e.preventDefault();
    handleFileDrop(e, folderId);
  };

  const uploadFromDragCard = (agentId, folderId) => {
    const selectedAgent = agents?.find((agent) => agent.id === agentId);

    if (!selectedAgent) {
      throw new Error("agent not found");
    }
    const updatedAgent = { ...selectedAgent, project_id: folderId };

    const agentsToCheckNames = agents?.filter(
      (f) => f.project_id === myCollectionId,
    );

    const newName = addVersionToDuplicates(
      updatedAgent,
      agentsToCheckNames ?? [],
    );

    updatedAgent.name = newName;

    setFolderDragging(false);
    setFolderIdDragging("");

    saveAgent(updatedAgent);
  };

  const uploadFormData = (data, folderId) => {
    const formData = new FormData();
    formData.append("file", data);
    setFolderDragging(false);
    setFolderIdDragging("");

    uploadAgentToFolder({ agents: formData, folderId });
  };

  return {
    dragOver,
    dragEnter,
    dragLeave,
    onDrop,
  };
};

export default useFileDrop;
