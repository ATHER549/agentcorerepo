import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StickToBottom } from "use-stick-to-bottom";
import MothersonLogo from "@/assets/mothersonLogo.svg?react";
import { TextEffectPerChar } from "@/components/ui/textAnimation";
import CustomChatInput from "@/customization/components/custom-chat-input";
import { ENABLE_IMAGE_ON_PLAYGROUND } from "@/customization/feature-flags";
import useCustomUseFileHandler from "@/customization/hooks/use-custom-use-file-handler";
import { track } from "@/customization/utils/analytics";
import { useGetAgentId } from "@/modals/IOModal/hooks/useGetAgentId";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useMessagesStore } from "@/stores/messagesStore";
import { useUtilityStore } from "@/stores/utilityStore";
import { useVoiceStore } from "@/stores/voiceStore";
import { cn } from "@/utils/utils";
import useTabVisibility from "../../../../../shared/hooks/use-tab-visibility";
import useAgentStore from "../../../../../stores/agentStore";
import type { ChatMessageType } from "../../../../../types/chat";
import type { chatViewProps } from "../../../../../types/components";
import AgentRunningSqueleton from "../../agent-running-squeleton";
import useDragAndDrop from "../chatInput/hooks/use-drag-and-drop";
import ChatMessage from "../chatMessage/chat-message";
import sortSenderMessages from "../helpers/sort-sender-messages";

const MemoizedChatMessage = memo(ChatMessage, (prevProps, nextProps) => {
  return (
    prevProps.chat.message === nextProps.chat.message &&
    prevProps.chat.id === nextProps.chat.id &&
    prevProps.chat.session === nextProps.chat.session &&
    prevProps.chat.content_blocks === nextProps.chat.content_blocks &&
    prevProps.chat.properties === nextProps.chat.properties &&
    prevProps.lastMessage === nextProps.lastMessage &&
    prevProps.hitlDoneMap === nextProps.hitlDoneMap
  );
});

export default function ChatView({
  sendMessage,
  visibleSession,
  focusChat,
  closeChat,
  playgroundPage,
  sidebarOpen,
}: chatViewProps): JSX.Element {
  const inputs = useAgentStore((state) => state.inputs);
  const realAgentId = useAgentsManagerStore((state) => state.currentAgentId);
  const currentAgentId = useGetAgentId();
  const [chatHistory, setChatHistory] = useState<ChatMessageType[] | undefined>(
    undefined,
  );
  const messages = useMessagesStore((state) => state.messages);
  const nodes = useAgentStore((state) => state.nodes);
  const chatInput = inputs.find((input) => input.type === "ChatInput");
  const chatInputNode = nodes.find((node) => node.id === chatInput?.id);
  const displayLoadingMessage = useMessagesStore(
    (state) => state.displayLoadingMessage,
  );

  const isBuilding = useAgentStore((state) => state.isBuilding);

  const inputTypes = inputs.map((obj) => obj.type);
  const updateAgentPool = useAgentStore((state) => state.updateAgentPool);
  const setChatValueStore = useUtilityStore((state) => state.setChatValueStore);
  const isTabHidden = useTabVisibility();

  // HITL: track resolved decisions — both from callback and from chat history.
  // Manual map captures the click immediately; derived map handles page refreshes.
  const [manualHitlMap, setManualHitlMap] = useState<Record<string, string>>({});
  const handleHitlDone = useCallback(
    (chatId: string, action: string) =>
      setManualHitlMap((prev) => ({ ...prev, [chatId]: action })),
    [],
  );

  //build chat history
  useEffect(() => {
    const messagesFromMessagesStore: ChatMessageType[] = messages
      .filter(
        (message) =>
          message.agent_id === currentAgentId &&
          (visibleSession === message.session_id || visibleSession === null),
      )
      .map((message) => {
        let files = message.files;
        // Handle the "[]" case, empty string, or already parsed array
        if (Array.isArray(files)) {
          // files is already an array, no need to parse
        } else if (files === "[]" || files === "") {
          files = [];
        } else if (typeof files === "string") {
          try {
            files = JSON.parse(files);
          } catch (error) {
            console.error("Error parsing files:", error);
            files = [];
          }
        }
        return {
          isSend: message.sender === "User",
          message: message.text,
          sender_name: message.sender_name,
          files: files,
          id: message.id,
          timestamp: message.timestamp,
          session: message.session_id,
          edit: message.edit,
          background_color: message.background_color || "",
          text_color: message.text_color || "",
          content_blocks: message.content_blocks || [],
          category: message.category || "",
          properties: message.properties || {},
        };
      });

    const finalChatHistory = [...messagesFromMessagesStore].sort(
      sortSenderMessages,
    );

    if (messages.length === 0 && !isBuilding && chatInputNode && isTabHidden) {
      setChatValueStore(
        chatInputNode.data.node.template["input_value"].value ?? "",
      );
    }

    setChatHistory(finalChatHistory);
  }, [messages, visibleSession]);

  // Derive HITL resolved state from chat history: scan for "Human review
  // completed" messages that follow an HITL message, then merge with the
  // manual map (captures the click immediately before messages refetch).
  const hitlDoneMap = useMemo(() => {
    const derived: Record<string, string> = {};
    if (chatHistory) {
      // Find HITL messages and check if a resolution message follows them
      const hitlMsgIds: string[] = [];
      for (const msg of chatHistory) {
        if (!msg.isSend && (msg.properties as any)?.hitl === true && msg.id) {
          hitlMsgIds.push(String(msg.id));
        }
        // Check if this message is a "Human review completed" resolution
        const text = String(msg.message ?? "");
        const match = text.match(/^[✓✗]\s*(\S+)\s*—\s*Human review completed/);
        if (match && hitlMsgIds.length > 0) {
          // Resolve the most recent unresolved HITL message
          for (const hid of [...hitlMsgIds].reverse()) {
            if (!derived[hid]) {
              derived[hid] = match[1];
              break;
            }
          }
        }
      }
    }
    return { ...derived, ...manualHitlMap };
  }, [chatHistory, manualHitlMap]);

  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (ref.current && focusChat) {
      ref.current.focus();
    }
    // trigger focus on chat when new session is set
  }, [focusChat]);

  function updateChat(chat: ChatMessageType, message: string) {
    chat.message = message;
    if (chat.componentId)
      updateAgentPool(chat.componentId, {
        message,
        sender_name: chat.sender_name ?? "Bot",
        sender: chat.isSend ? "User" : "Machine",
      });
  }

  const { files, setFiles, handleFiles } = useCustomUseFileHandler(realAgentId);
  const [isDragging, setIsDragging] = useState(false);

  const { dragOver, dragEnter, dragLeave } = useDragAndDrop(
    setIsDragging,
    !!playgroundPage,
  );

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    if (!ENABLE_IMAGE_ON_PLAYGROUND && playgroundPage) {
      e.stopPropagation();
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
      e.dataTransfer.clearData();
    }
    setIsDragging(false);
  };

  const agentRunningSkeletonMemo = useMemo(() => <AgentRunningSqueleton />, []);
  const isVoiceAssistantActive = useVoiceStore(
    (state) => state.isVoiceAssistantActive,
  );

  return (
    <StickToBottom
      className={cn(
        "flex h-full min-h-0 w-full flex-col",
        sidebarOpen &&
          !isVoiceAssistantActive &&
          "pointer-events-none blur-sm lg:pointer-events-auto lg:blur-0",
      )}
      onDragOver={dragOver}
      onDragEnter={dragEnter}
      onDragLeave={dragLeave}
      onDrop={onDrop}
      resize="smooth"
      initial="instant"
      mass={1}
    >
      <StickToBottom.Content className="flex min-h-0 flex-1 flex-col px-4 pb-3 pt-2 md:px-6">
        <div className="mx-auto flex h-full w-full max-w-4xl flex-1 flex-col overflow-hidden rounded-xl border border-border bg-background">
          <div className="flex min-h-0 flex-1 flex-col px-4 py-4 md:px-6">
          {chatHistory &&
            (isBuilding || chatHistory?.length > 0 ? (
              chatHistory?.map((chat, index) => (
                <MemoizedChatMessage
                  chat={chat}
                  lastMessage={chatHistory.length - 1 === index}
                  key={`${chat.id}-${index}`}
                  updateChat={updateChat}
                  closeChat={closeChat}
                  playgroundPage={playgroundPage}
                  hitlDoneMap={hitlDoneMap}
                  onHitlDone={handleHitlDone}
                />
              ))
            ) : (
              <div className="flex w-full flex-grow flex-col items-center justify-center">
                <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-muted/30 p-8">
                  <MothersonLogo
                    title="Motherson Logo"
                    className="h-9 w-9"
                  />
                  <div className="flex flex-col items-center justify-center">
                    <h3 className="pb-1 text-xl font-semibold text-primary">
                      New chat
                    </h3>
                    <p
                      className="text-base text-muted-foreground"
                      data-testid="new-chat-text"
                    >
                      <TextEffectPerChar>
                        Test your agent with a chat prompt
                      </TextEffectPerChar>
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </StickToBottom.Content>

      {displayLoadingMessage &&
        !(chatHistory?.[chatHistory.length - 1]?.category === "error") && (
        <div className="flex shrink-0 justify-center py-3">
          {agentRunningSkeletonMemo}
        </div>
      )}

      <div className="shrink-0 border-t border-border bg-background px-4 pb-4 pt-3 md:px-6">
        <div className="mx-auto w-full max-w-4xl">
          <CustomChatInput
            playgroundPage={!!playgroundPage}
            noInput={!inputTypes.includes("ChatInput")}
            sendMessage={async ({ repeat, files }) => {
              await sendMessage({ repeat, files });
              track("Playground Message Sent");
            }}
            inputRef={ref}
            files={files}
            setFiles={setFiles}
            isDragging={isDragging}
          />
        </div>
      </div>
    </StickToBottom>
  );
}
