import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/utils/utils";
import IconComponent from "../../../components/common/genericIconComponent";
import type { ChatViewWrapperProps } from "../types/chat-view-wrapper";
import ChatView from "./chatView/components/chat-view";

export const ChatViewWrapper = ({
  selectedViewField,
  visibleSession,
  sessions,
  sidebarOpen,
  currentAgentId,
  setSidebarOpen,
  isPlayground,
  setvisibleSession,
  setSelectedViewField,
  messagesFetched,
  sessionId,
  sendMessage,
  canvasOpen,
  setOpen,
  playgroundTitle,
  playgroundPage,
}: ChatViewWrapperProps) => {
  return (
    <div
      className={cn(
        "flex h-full min-h-0 w-full flex-col bg-background",
        selectedViewField ? "hidden" : "",
      )}
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center justify-between border-b border-border px-4 text-base md:px-6",
          playgroundPage ? "justify-between" : "lg:justify-start",
        )}
      >
        <div className="flex items-center lg:hidden">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSidebarOpen(true)}
              className="h-8 w-8 rounded-md"
            >
              <IconComponent
                name="PanelLeftOpen"
                className="h-[18px] w-[18px] text-ring"
              />
            </Button>
          </div>
        </div>
        {visibleSession && sessions.length > 0 && (
          <div
            className={cn(
              "truncate text-center text-sm font-semibold",
              playgroundPage ? "px-3" : "mr-12 flex-grow lg:mr-0",
              sidebarOpen ? "blur-sm lg:blur-0" : "",
            )}
          >
            {visibleSession === currentAgentId
              ? "Default Session"
              : `${visibleSession}`}
          </div>
        )}
        <div
          className={cn(
            "flex items-center justify-center rounded-sm ring-offset-background transition-opacity focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
            playgroundPage ? "" : "h-8",
          )}
        >
         
          {!playgroundPage && <Separator orientation="vertical" />}
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {messagesFetched && (
          <ChatView
            focusChat={sessionId}
            sendMessage={sendMessage}
            visibleSession={visibleSession}
            closeChat={
              !canvasOpen
                ? undefined
                : () => {
                    setOpen(false);
                  }
            }
            playgroundPage={playgroundPage}
            sidebarOpen={sidebarOpen}
          />
        )}
      </div>
    </div>
  );
};
