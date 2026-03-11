import useAgentsManagerStore from "@/stores/agentsManagerStore";
import type { AgentType } from "@/types/agent";
import { useDebounce } from "../use-debounce";
import useSaveAgent from "./use-save-agent";

const useAutoSaveAgent = () => {
  const saveAgent = useSaveAgent();
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
  const autoSavingInterval = useAgentsManagerStore(
    (state) => state.autoSavingInterval,
  );

  const autoSaveAgent = useDebounce((agent?: AgentType) => {
    if (autoSaving) {
      saveAgent(agent);
    }
  }, autoSavingInterval);

  return autoSaveAgent;
};

export default useAutoSaveAgent;
