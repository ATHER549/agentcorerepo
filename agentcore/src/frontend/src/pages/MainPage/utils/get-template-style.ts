import { useTypesStore } from "@/stores/typesStore";
import type { AgentType } from "@/types/agent";
import { iconExists } from "@/utils/styleUtils";

export const useGetTemplateStyle = (
  agentData: AgentType,
): { getIcon: () => Promise<string> } => {
  const types = useTypesStore((state) => state.types);
  const getIcon = async () => {
    if (
      agentData.is_component &&
      agentData.data?.nodes[0].type === "genericNode"
    ) {
      const dataType = agentData.data?.nodes[0].data.type;
      const isGroup = !!agentData.data?.nodes[0].data.node?.agent;
      const icon = agentData.data?.nodes[0].data.node?.icon;
      const name = (await iconExists(dataType)) ? dataType : types[dataType];
      const iconName = icon || (isGroup ? "group_components" : name);
      return iconName;
    } else {
      return agentData.icon ?? "Workagent";
    }
  };

  return { getIcon };
};
