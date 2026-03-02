import { useCallback } from "react";
import { createRoot } from "react-dom/client";
import type { AgentType } from "@/types/agent";
import useAgentsManagerStore from "../../../../stores/agentsManagerStore";
import DragCardComponent from "../components/dragCardComponent";

const useDragStart = (data: AgentType) => {
  const getAgentById = useAgentsManagerStore((state) => state.getAgentById);

  const onDragStart = useCallback(
    (event) => {
      const image = <DragCardComponent data={data} />; // Replace with whatever you want here

      const ghost = document.createElement("div");
      ghost.style.transform = "translate(-10000px, -10000px)";
      ghost.style.position = "absolute";
      document.body.appendChild(ghost);
      event.dataTransfer.setDragImage(ghost, 0, 0);

      const root = createRoot(ghost);
      root.render(image);

      const agent = getAgentById(data.id);
      if (agent) {
        event.dataTransfer.setData("agent", JSON.stringify(data));
      }
    },
    [data],
  );

  return { onDragStart };
};

export default useDragStart;
