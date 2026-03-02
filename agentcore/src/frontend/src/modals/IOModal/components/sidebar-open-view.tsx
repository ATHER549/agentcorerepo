import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import useAgentStore from "@/stores/agentStore";
import { useVoiceStore } from "@/stores/voiceStore";
import IconComponent from "../../../components/common/genericIconComponent";
import type { SidebarOpenViewProps } from "../types/sidebar-open-view";
import SessionSelector from "./IOFieldView/components/session-selector";

export const SidebarOpenView = ({
  sessions,
  setSelectedViewField,
  setvisibleSession,
  handleDeleteSession,
  visibleSession,
  selectedViewField,
  playgroundPage,
  setActiveSession,
}: SidebarOpenViewProps) => {
  const setNewSessionCloseVoiceAssistant = useVoiceStore(
    (state) => state.setNewSessionCloseVoiceAssistant,
  );

  const setNewChatOnPlayground = useAgentStore(
    (state) => state.setNewChatOnPlayground,
  );

  return (
    <>
      <div className="flex h-full w-full flex-col">
        <div className="pb-2">
          <div className="mb-2 flex items-center justify-between rounded-md border border-border bg-background px-2.5 py-2">
            <div className="flex items-center gap-2 text-muted-foreground">
              <IconComponent
                name="MessagesSquare"
                className="h-[16px] w-[16px]"
              />
              <div className="text-xs font-semibold uppercase tracking-wide">
                Sessions
              </div>
            </div>
            <ShadTooltip styleClasses="z-50" content="New Chat">
              <div>
                <Button
                  data-testid="new-chat"
                  variant="outline"
                  className="flex h-8 items-center justify-center gap-1.5 rounded-md px-2.5 text-xs"
                  onClick={(_) => {
                    setvisibleSession(undefined);
                    setSelectedViewField(undefined);
                    setNewSessionCloseVoiceAssistant(true);
                    setNewChatOnPlayground(true);
                  }}
                >
                  <IconComponent
                    name="Plus"
                    className="h-[14px] w-[14px]"
                  />
                  New
                </Button>
              </div>
            </ShadTooltip>
          </div>
        </div>
        <div className="flex w-full flex-col gap-1">
          {sessions.map((session, index) => (
            <SessionSelector
              setSelectedView={setSelectedViewField}
              selectedView={selectedViewField}
              key={index}
              session={session}
              playgroundPage={playgroundPage}
              deleteSession={(session) => {
                handleDeleteSession(session);
                if (selectedViewField?.id === session) {
                  setSelectedViewField(undefined);
                }
              }}
              updateVisibleSession={(session) => {
                setvisibleSession(session);
              }}
              toggleVisibility={() => {
                setvisibleSession(session);
              }}
              isVisible={visibleSession === session}
              inspectSession={(session) => {
                setSelectedViewField({
                  id: session,
                  type: "Session",
                });
              }}
              setActiveSession={(session) => {
                setActiveSession(session);
              }}
            />
          ))}
        </div>
      </div>
    </>
  );
};
