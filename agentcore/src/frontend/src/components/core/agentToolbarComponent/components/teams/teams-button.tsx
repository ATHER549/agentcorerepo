import { useContext, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { AuthContext } from "@/contexts/authContext";
import useAgentStore from "@/stores/agentStore";
import TeamsPublishModal from "./teams-publish-modal";

const TeamsIcon = () => (
  <ForwardedIconComponent
    name="MessageSquareShare"
    className="h-4 w-4 transition-all"
    strokeWidth={1.5}
  />
);

const TeamsButton = () => {
  const [open, setOpen] = useState(false);
  const hasIO = useAgentStore((state) => state.hasIO);
  const { permissions } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const canPublish = can("edit_agents");

  if (!canPublish) {
    return (
      <ShadTooltip content="You don't have permission to publish to Teams">
        <div className="pointer-events-none">
          <div className="playground-btn-agent-toolbar cursor-not-allowed text-muted-foreground duration-150">
            <TeamsIcon />
            <span className="hidden md:block">Teams</span>
          </div>
        </div>
      </ShadTooltip>
    );
  }

  if (!hasIO) {
    return (
      <ShadTooltip content="Add Chat Input/Output to publish to Teams">
        <div className="pointer-events-none">
          <div className="playground-btn-agent-toolbar cursor-not-allowed text-muted-foreground duration-150">
            <TeamsIcon />
            <span className="hidden md:block">Teams</span>
          </div>
        </div>
      </ShadTooltip>
    );
  }

  return (
    <>
      <ShadTooltip content="Publish this agent to Microsoft Teams">
        <div
          data-testid="teams-publish-btn"
          className="playground-btn-agent-toolbar hover:bg-accent cursor-pointer"
          onClick={() => setOpen(true)}
        >
          <TeamsIcon />
          <span className="hidden md:block">Teams</span>
        </div>
      </ShadTooltip>
      <TeamsPublishModal open={open} setOpen={setOpen} />
    </>
  );
};

export default TeamsButton;
