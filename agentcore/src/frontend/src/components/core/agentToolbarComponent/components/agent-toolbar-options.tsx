import type { Dispatch, SetStateAction } from "react";
import useAgentStore from "@/stores/agentStore";
import PublishDropdown from "./deploy-dropdown";
import PlaygroundButton from "./playground-button";
import PublishButton from "./publish-button";
import PublishStatusBadge from "./publish-status-badge";
import TeamsButton from "./teams/teams-button";

type AgentToolbarOptionsProps = {
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
  openApiModal: boolean;
  setOpenApiModal: Dispatch<SetStateAction<boolean>>;
};
const AgentToolbarOptions = ({
  open,
  setOpen,
  openApiModal,
  setOpenApiModal,
}: AgentToolbarOptionsProps) => {
  const hasIO = useAgentStore((state) => state.hasIO);

  return (
    <div className="flex items-center gap-1.5">
      <div className="flex h-full w-auto gap-1.5 rounded-sm transition-all">
        <PlaygroundButton
          hasIO={hasIO}
          open={open}
          setOpen={setOpen}
          canvasOpen
        />
        
      </div>
      <div className="flex h-full w-auto gap-1.5 rounded-sm transition-all">
        <PublishStatusBadge />
        <PublishButton hasIO={hasIO} />
      </div>
      <div className="flex h-full w-full gap-1.5 rounded-sm transition-all">
        <TeamsButton />
      </div>
      {/* <PublishDropdown
        openApiModal={openApiModal}
        setOpenApiModal={setOpenApiModal}
      /> */}
    </div>
  );
};

export default AgentToolbarOptions;
