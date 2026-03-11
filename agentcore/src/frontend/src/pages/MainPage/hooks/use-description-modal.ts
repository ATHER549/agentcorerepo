import { useMemo } from "react";

const useDescriptionModal = (
  selectedAgentsComponentsCards: string[] | undefined,
  type: string | undefined,
) => {
  const getDescriptionModal = useMemo(() => {
    const getTypeLabel = (type) => {
      const labels = {
        all: "item",
        component: "component",
        agent: "agent",
      };
      return labels[type] || "";
    };

    const getPluralizedLabel = (type) => {
      const labels = {
        all: "items",
        component: "components",
        agent: "agents",
      };
      return labels[type] || "";
    };

    if (selectedAgentsComponentsCards?.length === 1) {
      return getTypeLabel(type);
    }
    return getPluralizedLabel(type);
  }, [selectedAgentsComponentsCards, type]);

  return getDescriptionModal;
};

export default useDescriptionModal;
