import AgentSettingsComponent from "@/components/core/agentSettingsComponent";
import type { AgentSettingsPropsType } from "../../types/components";
import BaseModal from "../baseModal";

export default function AgentSettingsModal({
  open,
  setOpen,
  agentData,
}: AgentSettingsPropsType): JSX.Element {
  if (!open) return <></>;
  return (
    <BaseModal
      open={open}
      setOpen={setOpen}
      size="small-update"
      className="p-4"
    >
      <BaseModal.Header>
        <span className="text-base font-semibold">agent Details</span>
      </BaseModal.Header>
      <BaseModal.Content>
        <AgentSettingsComponent
          agentData={agentData}
          close={() => setOpen(false)}
          open={open}
        />
      </BaseModal.Content>
    </BaseModal>
  );
}
