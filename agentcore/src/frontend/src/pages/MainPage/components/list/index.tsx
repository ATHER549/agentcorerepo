import { useContext, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import useDragStart from "@/components/core/cardComponent/hooks/use-on-drag-start";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useDeleteAgent from "@/hooks/agents/use-delete-agent";
import DeleteConfirmationModal from "@/modals/deleteConfirmationModal";
import ExportModal from "@/modals/exportModal";
import AgentSettingsModal from "@/modals/agentSettingsModal";
import useAlertStore from "@/stores/alertStore";
import type { AgentType } from "@/types/agent";
import { downloadAgent } from "@/utils/reactFlowUtils";
import { swatchColors } from "@/utils/styleUtils";
import { cn, getNumberFromString } from "@/utils/utils";
import { useGetPublishStatus } from "@/controllers/API/queries/agents/use-get-publish-status";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { AuthContext } from "@/contexts/authContext";
import useDescriptionModal from "../../hooks/use-description-modal";
import { timeElapsed } from "../../utils/time-elapse";
import DropdownComponent from "../dropdown";

const ListComponent = ({
  agentData,
  selected,
  setSelected,
  shiftPressed,
  index,
  disabled = false,
}: {
  agentData: AgentType;
  selected: boolean;
  setSelected: (selected: boolean) => void;
  shiftPressed: boolean;
  index: number;
  disabled?: boolean;
}) => {
  const navigate = useCustomNavigate();
  const [openDelete, setOpenDelete] = useState(false);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const { deleteAgent } = useDeleteAgent();
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const { folderId } = useParams();
  const [openSettings, setOpenSettings] = useState(false);
  const [openExportModal, setOpenExportModal] = useState(false);
  const { userData, role } = useContext(AuthContext);
  const currentUserId = String(userData?.id ?? "");
  const normalizedRole = String(role ?? "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  const isAdminRole = ["root", "super_admin", "department_admin", "admin", "root_admin"].includes(
    normalizedRole,
  );
  const isComponent = agentData.is_component ?? false;
  const { data: publishStatus } = useGetPublishStatus(
    { agent_id: agentData.id },
    { enabled: !isComponent, refetchInterval: 30000 },
  );
  const workflowLocked = !isComponent && Boolean(publishStatus?.has_pending_approval);
  const effectiveDisabled = disabled || workflowLocked;
  const latestDecision = (publishStatus?.latest_review_decision || "").toUpperCase();
  const latestProdStatus = (publishStatus?.latest_prod_status || "").toUpperCase();
  const requesterId = String(
    publishStatus?.pending_requested_by || publishStatus?.latest_prod_published_by || "",
  );
  const showRequesterBadge = !isComponent && !!requesterId && requesterId === currentUserId;
  const badgeLabel = workflowLocked
    ? "Awaiting Approval"
    : latestProdStatus === "PUBLISHED"
      ? "Approved"
      : latestDecision === "REJECTED"
        ? "Rejected"
        : "";

  const editAgentLink = `/agent/${agentData.id}${folderId ? `/folder/${folderId}` : ""}`;
  const readOnlyAgentLink = `/agent/${agentData.id}${folderId ? `/folder/${folderId}` : ""}?readonly=1`;
  const isAgentOwnedByCurrentUser = agentData.user_id
    ? String(agentData.user_id) === currentUserId
     : true;
  const shouldForceReadOnly = folderId && isAdminRole && !isAgentOwnedByCurrentUser;
  const canModifyAgent = !shouldForceReadOnly;

  const handleClick = async () => {
    if (effectiveDisabled) return; // Prevent click when disabled
    
    if (shiftPressed) {
      setSelected(!selected);
    } else {
      if (!isComponent) {
        // In project sections, admins should open agents in read-only mode.
        if (shouldForceReadOnly) {
          navigate(readOnlyAgentLink);
          return;
        }
        navigate(editAgentLink);
      }
    }
  };

  const handleDelete = () => {
    deleteAgent({ id: [agentData.id] })
      .then(() => {
        setSuccessData({
          title: "Selected items deleted successfully",
        });
      })
      .catch(() => {
        setErrorData({
          title: "Error deleting items",
          list: ["Please try again"],
        });
      });
  };

  const { onDragStart } = useDragStart(agentData);

  const descriptionModal = useDescriptionModal(
    [agentData?.id],
    agentData.is_component ? "component" : "agent",
  );

  const swatchIndex =
    (agentData.gradient && !isNaN(parseInt(agentData.gradient))
      ? parseInt(agentData.gradient)
      : getNumberFromString(agentData.gradient ?? agentData.id)) %
    swatchColors.length;

  const handleExport = () => {
    if (agentData.is_component) {
      downloadAgent(agentData, agentData.name, agentData.description);
      setSuccessData({ title: `${agentData.name} exported successfully` });
    } else {
      setOpenExportModal(true);
    }
  };

  return (
    <>
      <Card
        key={agentData.id}
        draggable={!effectiveDisabled}
        onDragStart={effectiveDisabled ? undefined : onDragStart}
        onClick={handleClick}
        className={cn(
          "flex flex-row bg-background group justify-between rounded-lg border-none px-4 py-3 shadow-none hover:bg-muted",
          isComponent || effectiveDisabled ? "cursor-default" : "cursor-pointer",
          effectiveDisabled && "opacity-70"
        )}
        data-testid="list-card"
      >
        <div
          className={`flex min-w-0 ${
            isComponent || effectiveDisabled ? "cursor-default" : "cursor-pointer"
          } items-center gap-4`}
        >
          <div className="group/checkbox relative flex items-center">
            <div
              className={cn(
                "z-20 flex w-0 items-center transition-all duration-300",
                selected && "w-10",
              )}
            >
              <Checkbox
                checked={selected}
                onCheckedChange={(checked) => setSelected(checked as boolean)}
                onClick={(e) => e.stopPropagation()}
                disabled={effectiveDisabled}
                className={cn(
                  "ml-2 transition-opacity focus-visible:ring-0",
                  !selected && "opacity-0 group-hover/checkbox:opacity-100",
                )}
                data-testid={`checkbox-${agentData.id}`}
              />
            </div>
            <div
              className={cn(
                "flex items-center justify-center rounded-lg p-1.5",
                index % 2 === 0 ? "bg-muted-foreground/30" : "bg-[var(--info-foreground)]",
              )}
            >
              <ForwardedIconComponent
                name="Workagent"
                className={cn(
                  "h-5 w-5",
                  index % 2 === 0 ? "text-foreground" : "text-white",
                )}
              />
            </div>
          </div>

          <div className="flex min-w-0 flex-col justify-start">
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
              <div
                className="flex min-w-0 flex-shrink truncate text-sm font-semibold"
                data-testid={`agent-name-div`}
              >
                <span
                  className="truncate"
                  data-testid={`agent-name-${agentData.id}`}
                >
                  {agentData.name}
                </span>
              </div>
              <div className="flex min-w-0 flex-shrink text-xs text-muted-foreground">
                <span className="truncate">
                  Edited {timeElapsed(agentData.updated_at)} ago
                </span>
              </div>
              {showRequesterBadge && !!badgeLabel && (
                <ShadTooltip
                  content={
                    workflowLocked
                      ? "PROD request is awaiting approval."
                      : latestDecision === "REJECTED"
                        ? "Your PROD publish request was rejected."
                        : latestProdStatus === "PUBLISHED"
                          ? "Your PROD publish request is approved."
                          : ""
                  }
                >
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-[10px] font-semibold",
                      workflowLocked && "bg-yellow-100 text-yellow-800",
                      !workflowLocked &&
                        latestProdStatus === "PUBLISHED" &&
                        "bg-green-100 text-green-800",
                      !workflowLocked &&
                        latestDecision === "REJECTED" &&
                        "bg-red-100 text-red-800",
                    )}
                  >
                    {badgeLabel}
                  </span>
                </ShadTooltip>
              )}
            </div>
          </div>
        </div>

        <div className="ml-5 flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild disabled={effectiveDisabled}>
              <Button
                variant="ghost"
                size="iconMd"
                data-testid="home-dropdown-menu"
                className="group"
                disabled={effectiveDisabled}
              >
                <ForwardedIconComponent
                  name="Ellipsis"
                  aria-hidden="true"
                  className="h-5 w-5 text-muted-foreground group-hover:text-foreground"
                />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className="w-[185px]"
              sideOffset={5}
              side="bottom"
            >
              <DropdownComponent
                agentData={agentData}
                setOpenDelete={setOpenDelete}
                handleExport={handleExport}
                handleEdit={() => {
                  setOpenSettings(true);
                }}
                canModifyAgent={canModifyAgent}
              />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </Card>
      {openDelete && (
        <DeleteConfirmationModal
          open={openDelete}
          setOpen={setOpenDelete}
          onConfirm={handleDelete}
          description={descriptionModal}
          note={!agentData.is_component ? "and its message history" : ""}
        />
      )}
      <ExportModal
        open={openExportModal}
        setOpen={setOpenExportModal}
        agentData={agentData}
      />
      <AgentSettingsModal
        open={openSettings}
        setOpen={setOpenSettings}
        agentData={agentData}
      />
    </>
  );
};

export default ListComponent;



