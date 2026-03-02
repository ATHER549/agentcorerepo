import { type Dispatch, type SetStateAction, useState } from "react";
import { useHref } from "react-router-dom";
import IconComponent from "@/components/common/genericIconComponent";
import ShadTooltipComponent from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { usePatchUpdateAgent } from "@/controllers/API/queries/agents/use-patch-update-agent";
import { CustomLink } from "@/customization/components/custom-link";
import { ENABLE_PUBLISH, ENABLE_WIDGET } from "@/customization/feature-flags";
import { customMcpOpen } from "@/customization/utils/custom-mcp-open";
import ApiModal from "@/modals/apiModal";
import EmbedModal from "@/modals/EmbedModal/embed-modal";
import ExportModal from "@/modals/exportModal";
import useAlertStore from "@/stores/alertStore";
import useAuthStore from "@/stores/authStore";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { cn } from "@/utils/utils";

type PublishDropdownProps = {
  openApiModal: boolean;
  setOpenApiModal: Dispatch<SetStateAction<boolean>>;
};

export default function PublishDropdown({
  openApiModal,
  setOpenApiModal,
}: PublishDropdownProps) {
  const location = useHref("/");
  const domain = window.location.origin + location;
  const [openEmbedModal, setOpenEmbedModal] = useState(false);
  const currentAgent = useAgentsManagerStore((state) => state.currentAgent);
  const agentId = currentAgent?.id;
  const agentName = currentAgent?.name;
  const folderId = currentAgent?.project_id;
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const { mutateAsync } = usePatchUpdateAgent();
  const agents = useAgentsManagerStore((state) => state.agents);
  const setAgents = useAgentsManagerStore((state) => state.setAgents);
  const setCurrentAgent = useAgentStore((state) => state.setCurrentAgent);
  const isPublished = currentAgent?.access_type === "PUBLIC";
  const hasIO = useAgentStore((state) => state.hasIO);
  const isAuth = useAuthStore((state) => !!state.autoLogin);
  const [openExportModal, setOpenExportModal] = useState(false);

  const handlePublishedSwitch = async (checked: boolean) => {
    mutateAsync(
      {
        id: agentId ?? "",
        access_type: checked ? "PRIVATE" : "PUBLIC",
      },
      {
        onSuccess: (updatedAgent) => {
          if (agents) {
            setAgents(
              agents.map((agent) => {
                if (agent.id === updatedAgent.id) {
                  return updatedAgent;
                }
                return agent;
              }),
            );
            setCurrentAgent(updatedAgent);
          } else {
            setErrorData({
              title: "Failed to save agent",
              list: ["Agents variable undefined"],
            });
          }
        },
        onError: (e) => {
          setErrorData({
            title: "Failed to save agent",
            list: [e.message],
          });
        },
      },
    );
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="md"
            className="!px-2.5 font-normal"
            data-testid="publish-button"
          >
            Share
            <IconComponent name="ChevronDown" className="!h-5 !w-5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          forceMount
          sideOffset={7}
          alignOffset={-2}
          align="end"
          className="w-full min-w-[275px]"
        >
          <DropdownMenuItem
            className="deploy-dropdown-item group"
            onClick={() => setOpenApiModal(true)}
            data-testid="api-access-item"
          >
            <IconComponent name="Code2" className={`icon-size mr-2`} />
            <span>API access</span>
          </DropdownMenuItem>
          <DropdownMenuItem
            className="deploy-dropdown-item group"
            onClick={() => setOpenExportModal(true)}
          >
            <IconComponent name="Download" className={`icon-size mr-2`} />
            <span>Export</span>
          </DropdownMenuItem>
          <CustomLink
            className={cn("flex-1")}
            to={`/mcp/folder/${folderId}`}
            target={customMcpOpen()}
          >
            <DropdownMenuItem
              className="deploy-dropdown-item group"
              onClick={() => {}}
              data-testid="mcp-server-item"
            >
              <IconComponent name="Mcp" className={`icon-size mr-2`} />
              <span>MCP Server</span>
              <IconComponent
                name="ExternalLink"
                className={`icon-size ml-auto hidden group-hover:block`}
              />
            </DropdownMenuItem>
          </CustomLink>
          {ENABLE_WIDGET && (
            <DropdownMenuItem
              onClick={() => setOpenEmbedModal(true)}
              className="deploy-dropdown-item group"
            >
              <IconComponent name="Columns2" className={`icon-size mr-2`} />
              <span>Embed into site</span>
            </DropdownMenuItem>
          )}

          {ENABLE_PUBLISH && (
            <DropdownMenuItem
              className="deploy-dropdown-item group"
              disabled={!hasIO}
              onClick={() => {}}
              data-testid="shareable-playground"
            >
              <div className="flex w-full items-center justify-between">
                <div className="flex items-center">
                  <ShadTooltipComponent
                    styleClasses="truncate"
                    side="left"
                    content={
                      hasIO
                        ? isPublished
                          ? encodeURI(`${domain}/playground/${agentId}`)
                          : "Activate to share a public version of this Playground"
                        : "Add a Chat Input or Chat Output to access your agent"
                    }
                  >
                    <div className="flex items-center">
                      <IconComponent
                        name="Globe"
                        className={cn(
                          `icon-size mr-2`,
                          !isPublished && "opacity-50",
                        )}
                      />

                      {isPublished ? (
                        <CustomLink
                          className="flex-1"
                          to={`/playground/${agentId}`}
                          target="_blank"
                        >
                          <span>Shareable Playground</span>
                        </CustomLink>
                      ) : (
                        <span className={cn(!isPublished && "opacity-50")}>
                          Shareable Playground
                        </span>
                      )}
                    </div>
                  </ShadTooltipComponent>
                </div>
                <Switch
                  data-testid="publish-switch"
                  className="scale-[85%]"
                  checked={isPublished}
                  disabled={!hasIO}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handlePublishedSwitch(isPublished);
                  }}
                />
              </div>
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <ApiModal open={openApiModal} setOpen={setOpenApiModal}>
        <></>
      </ApiModal>
      <EmbedModal
        open={openEmbedModal}
        setOpen={setOpenEmbedModal}
        agentId={agentId ?? ""}
        agentName={agentName ?? ""}
        isAuth={isAuth}
        tweaksBuildedObject={{}}
        activeTweaks={false}
      ></EmbedModal>
      <ExportModal open={openExportModal} setOpen={setOpenExportModal} />
    </>
  );
}
