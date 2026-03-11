import {
  ControlButton,
  Panel,
  type reactFlowState,
  useReactFlow,
  useStore,
  useStoreApi,
} from "@xyflow/react";
import { cloneDeep } from "lodash";
import { useCallback, useEffect } from "react";
import { useShallow } from "zustand/react/shallow";
import { shallow } from "zustand/shallow";
import IconComponent from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import useSaveAgent from "@/hooks/agents/use-save-agent";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { cn } from "@/utils/utils";

type CustomControlButtonProps = {
  iconName: string;
  tooltipText: string;
  onClick: () => void;
  disabled?: boolean;
  backgroundClasses?: string;
  iconClasses?: string;
  testId?: string;
};

export const CustomControlButton = ({
  iconName,
  tooltipText,
  onClick,
  disabled,
  backgroundClasses,
  iconClasses,
  testId,
}: CustomControlButtonProps): JSX.Element => {
  return (
    <ControlButton
      data-testid={testId}
      className="group !h-8 !w-8 rounded !p-0"
      onClick={onClick}
      disabled={disabled}
      title={testId?.replace(/_/g, " ")}
    >
      <ShadTooltip content={tooltipText} side="right">
        <div className={cn("rounded p-2.5", backgroundClasses)}>
          <IconComponent
            name={iconName}
            aria-hidden="true"
            className={cn(
              "scale-150 text-muted-foreground group-hover:text-primary",
              iconClasses,
            )}
          />
        </div>
      </ShadTooltip>
    </ControlButton>
  );
};

const selector = (s: reactFlowState) => ({
  isInteractive: s.nodesDraggable || s.nodesConnectable || s.elementsSelectable,
  minZoomReached: s.transform[2] <= s.minZoom,
  maxZoomReached: s.transform[2] >= s.maxZoom,
});

const CanvasControls = ({ children }) => {
  const store = useStoreApi();
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  const { isInteractive, minZoomReached, maxZoomReached } = useStore(
    selector,
    shallow,
  );
  const saveAgent = useSaveAgent();
  const isLocked = useAgentStore(
    useShallow((state) => state.currentAgent?.locked),
  );
  const setCurrentAgent = useAgentStore((state) => state.setCurrentAgent);
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
  const setHelperLineEnabled = useAgentStore(
    (state) => state.setHelperLineEnabled,
  );
  const helperLineEnabled = useAgentStore((state) => state.helperLineEnabled);

  useEffect(() => {
    store.setState({
      nodesDraggable: !isLocked,
      nodesConnectable: !isLocked,
      elementsSelectable: !isLocked,
    });
  }, [isLocked]);

  const handleSaveAgent = useCallback(() => {
    const currentAgent = useAgentStore.getState().currentAgent;
    if (!currentAgent) return;
    const newAgent = cloneDeep(currentAgent);
    newAgent.locked = isInteractive;
    if (autoSaving) {
      saveAgent(newAgent);
    } else {
      setCurrentAgent(newAgent);
    }
  }, [isInteractive, autoSaving, saveAgent, setCurrentAgent]);

  const onToggleInteractivity = useCallback(() => {
    store.setState({
      nodesDraggable: !isInteractive,
      nodesConnectable: !isInteractive,
      elementsSelectable: !isInteractive,
    });
    handleSaveAgent();
  }, [isInteractive, store, handleSaveAgent]);

  const onToggleHelperLines = useCallback(() => {
    setHelperLineEnabled(!helperLineEnabled);
  }, [setHelperLineEnabled, helperLineEnabled]);

  return (
    <Panel
      data-testid="canvas_controls"
      className="react-flow__controls !left-auto !m-2 flex !flex-col gap-1.5 rounded-md border border-border bg-background fill-foreground stroke-foreground p-0.5 text-primary [&>button]:border-0 [&>button]:bg-background hover:[&>button]:bg-accent"
      position="bottom-left"
    >
      {/* Zoom In */}
      <CustomControlButton
        iconName="ZoomIn"
        tooltipText="Zoom In"
        onClick={zoomIn}
        disabled={maxZoomReached}
        testId="zoom_in"
      />
      {/* Zoom Out */}
      <CustomControlButton
        iconName="ZoomOut"
        tooltipText="Zoom Out"
        onClick={zoomOut}
        disabled={minZoomReached}
        testId="zoom_out"
      />
      {/* Zoom To Fit */}
      <CustomControlButton
        iconName="maximize"
        tooltipText="Fit To Zoom"
        onClick={fitView}
        testId="fit_view"
      />
      {children}
      {/* Lock/Unlock */}
      <CustomControlButton
        iconName={isInteractive ? "LockOpen" : "Lock"}
        tooltipText={isInteractive ? "Lock" : "Unlock"}
        onClick={onToggleInteractivity}
        backgroundClasses={isInteractive ? "" : "bg-destructive"}
        iconClasses={
          isInteractive ? "" : "text-primary-foreground dark:text-primary"
        }
        testId="lock_unlock"
      />
      {/* Display Helper Lines */}
      <CustomControlButton
        iconName={helperLineEnabled ? "FoldHorizontal" : "UnfoldHorizontal"}
        tooltipText={
          helperLineEnabled ? "Hide Helper Lines" : "Show Helper Lines"
        }
        onClick={onToggleHelperLines}
        backgroundClasses={cn(helperLineEnabled && "bg-muted")}
        iconClasses={cn(helperLineEnabled && "text-muted-foreground")}
        testId="helper_lines"
      />
    </Panel>
  );
};

export default CanvasControls;
