import { Panel, useStoreApi } from "@xyflow/react";
import { type ReactNode, useEffect } from "react";
import { useShallow } from "zustand/react/shallow";
import { Separator } from "@/components/ui/separator";
import useAgentStore from "@/stores/agentStore";
import CanvasControlsDropdown from "./CanvasControlsDropdown";

const CanvasControls = ({ children }: { children?: ReactNode }) => {
  const reactFlowStoreApi = useStoreApi();
  const isAgentLocked = useAgentStore(
    useShallow((state) => state.currentAgent?.locked),
  );

  useEffect(() => {
    reactFlowStoreApi.setState({
      nodesDraggable: !isAgentLocked,
      nodesConnectable: !isAgentLocked,
      elementsSelectable: !isAgentLocked,
    });
  }, [isAgentLocked, reactFlowStoreApi]);

  return (
    <Panel
      data-testid="main_canvas_controls"
      className="react-flow__controls !left-auto !m-2 flex !flex-row rounded-md border border-border bg-background fill-foreground stroke-foreground text-primary [&>button]:border-0"
      position="bottom-right"
    >
      {children}
      {children && (
        <span>
          <Separator orientation="vertical" />
        </span>
      )}
      <CanvasControlsDropdown />
    </Panel>
  );
};

export default CanvasControls;
