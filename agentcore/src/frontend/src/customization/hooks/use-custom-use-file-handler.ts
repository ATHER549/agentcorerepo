import { useFileHandler } from "@/modals/IOModal/components/chatView/chatInput/hooks/use-file-handler";

export const customUseFileHandler = (currentAgentId: string) => {
  return useFileHandler(currentAgentId);
};

export default customUseFileHandler;
