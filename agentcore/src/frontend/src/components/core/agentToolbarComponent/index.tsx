import { Panel } from "@xyflow/react";
import { memo, useEffect, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import IconComponent from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import { track } from "@/customization/utils/analytics";
import ExportModal from "@/modals/exportModal";
import TemplatesModal from "@/modals/templatesModal";
import useSaveAgent from "@/hooks/agents/use-save-agent";
import { useAddComponent } from "@/hooks/use-add-component";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import useAgentStore from "../../../stores/agentStore";
import useAgentsManagerStore from "../../../stores/agentsManagerStore";
import { useShortcutsStore } from "../../../stores/shortcuts";
import { useTypesStore } from "../../../stores/typesStore";
import { cn, isThereModal } from "../../../utils/utils";
import AgentToolbarOptions from "./components/agent-toolbar-options";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext"; 

const AgentToolbar = memo(function AgentToolbar(): JSX.Element {
  const { permissions, role } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const preventDefault = true;
  const [open, setOpen] = useState<boolean>(false);
  const [openApiModal, setOpenApiModal] = useState<boolean>(false);
  const [openExportModal, setOpenExportModal] = useState<boolean>(false);
  const [openTemplatesModal, setOpenTemplatesModal] = useState<boolean>(false);
  const saveAgent = useSaveAgent();
  const addComponent = useAddComponent();
  const data = useTypesStore((state) => state.data);
  const undo = useAgentsManagerStore((state) => state.undo);
  const redo = useAgentsManagerStore((state) => state.redo);
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
  const saveLoading = useAgentsManagerStore((state) => state.saveLoading);
  const isBuilding = useAgentStore((state) => state.isBuilding);
  const changesNotSaved = useUnsavedChanges();
  const updatedAt = useAgentsManagerStore((state) => state.currentAgent?.updated_at);
  const reactFlowInstance = useAgentStore((state) => state.reactFlowInstance);
  
  const handleAPIWShortcut = (e: KeyboardEvent) => {
    if (isThereModal() && !openApiModal) return;
    setOpenApiModal((oldOpen) => !oldOpen);
  };

  const handleChatWShortcut = (e: KeyboardEvent) => {
    if (isThereModal() && !open) return;
    if (!can("edit_agents")) return;
    if (useAgentStore.getState().hasIO) {
      setOpen((oldState) => !oldState);
    }
  };

  const handleShareWShortcut = (e: KeyboardEvent) => {
    if (isThereModal() && !openExportModal) return;
    setOpenExportModal((oldState) => !oldState);
  };

  const openPlayground = useShortcutsStore((state) => state.openPlayground);
  const api = useShortcutsStore((state) => state.api);
  const agent = useShortcutsStore((state) => state.agent);

  useHotkeys(openPlayground, handleChatWShortcut, { preventDefault });
  useHotkeys(api, handleAPIWShortcut, { preventDefault });
  useHotkeys(agent, handleShareWShortcut, { preventDefault });

  useEffect(() => {
    if (open) {
      track("Playground Button Clicked");
    }
  }, [open]);

  const handleSave = () => {
    saveAgent();
  };

  const customComponent = data?.["custom_component"]?.["CustomComponent"] ?? null;

  const autoSaveStatus = autoSaving
    ? saveLoading
      ? "Auto-saving..."
      : updatedAt
        ? `Auto-saved at ${new Date(updatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
        : changesNotSaved
          ? "Unsaved changes"
          : "Auto-save on"
    : "Auto-save off";

  return (
    <>
      <Panel className="!left-0 !right-0 !top-0 !m-0 !w-full" position="top-left">
        <div
          className={cn(
            "flex h-11 w-full items-center justify-between border-b bg-background px-2",
          )}
        >
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
              <ShadTooltip content="Undo">
                <Button
                  variant="ghost"
                  size="iconSm"
                  className="h-7 w-7"
                  onClick={undo}
                  data-testid="navbar-undo-button"
                >
                  <IconComponent name="Undo" className="h-4 w-4" />
                </Button>
              </ShadTooltip>
              <ShadTooltip content="Redo">
                <Button
                  variant="ghost"
                  size="iconSm"
                  className="h-7 w-7"
                  onClick={redo}
                  data-testid="navbar-redo-button"
                >
                  <IconComponent name="Redo" className="h-4 w-4" />
                </Button>
              </ShadTooltip>
              <ShadTooltip content="Zoom In">
                <Button
                  variant="ghost"
                  size="iconSm"
                  className="h-7 w-7"
                  onClick={() => reactFlowInstance?.zoomIn?.()}
                  data-testid="navbar-zoom-plus-button"
                >
                  <IconComponent name="Plus" className="h-4 w-4" />
                </Button>
              </ShadTooltip>
              <ShadTooltip content="Zoom Out">
                <Button
                  variant="ghost"
                  size="iconSm"
                  className="h-7 w-7"
                  onClick={() => reactFlowInstance?.zoomOut?.()}
                  data-testid="navbar-zoom-minus-button"
                >
                  <IconComponent name="Minus" className="h-4 w-4" />
                </Button>
              </ShadTooltip>
            </div>

            <div className="h-5 w-px bg-border" />

            <Button
              variant="outline"
              size="sm"
              onClick={() => setOpenTemplatesModal(true)}
              data-testid="navbar-templates-button"
            >
              <IconComponent name="LayoutPanelTop" className="h-4 w-4" />
              Templates
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!customComponent}
              onClick={() => {
                if (customComponent) {
                  addComponent(customComponent, "CustomComponent");
                }
              }}
              data-testid="navbar-custom-code-button"
            >
              <IconComponent name="Plus" className="h-4 w-4" />
              Create Custom
            </Button>

            <div className="h-5 w-px bg-border" />

            <ShadTooltip content={autoSaving ? "Turn off auto-save in settings to enable manual save only" : "Save agent"}>
              <div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!changesNotSaved || isBuilding || saveLoading}
                  onClick={handleSave}
                  data-testid="navbar-save-button"
                >
                  <IconComponent
                    name={saveLoading ? "Loader2" : "Save"}
                    className={cn("h-4 w-4", saveLoading && "animate-spin")}
                  />
                  Save
                </Button>
              </div>
            </ShadTooltip>
            <span className="text-xs text-muted-foreground" data-testid="navbar-autosave-status">
              {autoSaveStatus}
            </span>
          </div>
          <AgentToolbarOptions
            open={open}
            setOpen={setOpen}
            openApiModal={openApiModal}
            setOpenApiModal={setOpenApiModal}
          />
        </div>
      </Panel>
      <ExportModal open={openExportModal} setOpen={setOpenExportModal} />
      <TemplatesModal open={openTemplatesModal} setOpen={setOpenTemplatesModal} />
    </>
  );
});

export default AgentToolbar;
