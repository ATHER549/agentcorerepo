import Convert from "ansi-to-html";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ContentBlockDisplay } from "@/components/core/chatComponents/ContentBlockDisplay";
import { useUpdateMessage } from "@/controllers/API/queries/messages";
import { CustomMarkdownField } from "@/customization/components/custom-markdown-field";
import { CustomProfileIcon } from "@/customization/components/custom-profile-icon";
import { ENABLE_AGENTCORE } from "@/customization/feature-flags";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useMessagesStore } from "@/stores/messagesStore";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import Robot from "../../../../../assets/robot.png";
import IconComponent, {
  ForwardedIconComponent,
} from "../../../../../components/common/genericIconComponent";
import SanitizedHTMLWrapper from "../../../../../components/common/sanitizedHTMLWrapper";
import { EMPTY_INPUT_SEND_MESSAGE } from "../../../../../constants/constants";
import useAlertStore from "../../../../../stores/alertStore";
import type { chatMessagePropsType } from "../../../../../types/components";
import { cn } from "../../../../../utils/utils";
import { ErrorView } from "./components/content-view";
import EditMessageField from "./components/edit-message-field";
import FileCardWrapper from "./components/file-card-wrapper";
import { EditMessageButton } from "./components/message-options";
import { convertFiles } from "./helpers/convert-files";

export default function ChatMessage({
  chat,
  lastMessage,
  updateChat,
  closeChat,
  playgroundPage,
  hitlDoneMap = {},
  onHitlDone,
}: chatMessagePropsType): JSX.Element {
  const convert = new Convert({ newline: true });
  const [hidden, setHidden] = useState(true);
  const [streamUrl, setStreamUrl] = useState(chat.stream_url);
  const agent_id = useAgentsManagerStore((state) => state.currentAgentId);
  const fitViewNode = useAgentStore((state) => state.fitViewNode);
  // We need to check if message is not undefined because
  // we need to run .toString() on it
  const [chatMessage, setChatMessage] = useState(
    chat.message ? chat.message.toString() : "",
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const eventSource = useRef<EventSource | undefined>(undefined);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const chatMessageRef = useRef(chatMessage);
  const [editMessage, setEditMessage] = useState(false);
  const [showError, setShowError] = useState(false);
  const isBuilding = useAgentStore((state) => state.isBuilding);
  const queryClient = useQueryClient();

  const isAudioMessage = chat.category === "audio";

  useEffect(() => {
    const chatMessageString = chat.message ? chat.message.toString() : "";
    setChatMessage(chatMessageString);
    chatMessageRef.current = chatMessage;
  }, [chat, isBuilding]);

  // The idea now is that chat.stream_url MAY be a URL if we should stream the output of the chat
  // probably the message is empty when we have a stream_url
  // what we need is to update the chat_message with the SSE data
  const streamChunks = (url: string) => {
    setIsStreaming(true); // Streaming starts
    return new Promise<boolean>((resolve, reject) => {
      eventSource.current = new EventSource(url);
      eventSource.current.onmessage = (event) => {
        const parsedData = JSON.parse(event.data);
        if (parsedData.chunk) {
          setChatMessage((prev) => prev + parsedData.chunk);
        }
      };
      eventSource.current.onerror = (event: any) => {
        setIsStreaming(false);
        eventSource.current?.close();
        setStreamUrl(undefined);
        if (JSON.parse(event.data)?.error) {
          setErrorData({
            title: "Error on Streaming",
            list: [JSON.parse(event.data)?.error],
          });
        }
        updateChat(chat, chatMessageRef.current);
        reject(new Error("Streaming failed"));
      };
      eventSource.current.addEventListener("close", (event) => {
        setStreamUrl(undefined); // Update state to reflect the stream is closed
        eventSource.current?.close();
        setIsStreaming(false);
        resolve(true);
      });
    });
  };

  useEffect(() => {
    if (streamUrl && !isStreaming) {
      streamChunks(streamUrl)
        .then(() => {
          if (updateChat) {
            updateChat(chat, chatMessageRef.current);
          }
        })
        .catch((error) => {
          console.error(error);
        });
    }
  }, [streamUrl, chatMessage]);
  useEffect(() => {
    return () => {
      eventSource.current?.close();
    };
  }, []);

  useEffect(() => {
    if (chat.category === "error") {
      // Short delay before showing error to allow for loading animation
      const timer = setTimeout(() => {
        setShowError(true);
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [chat.category]);

  let decodedMessage = chatMessage ?? "";
  try {
    decodedMessage = decodeURIComponent(chatMessage);
  } catch (_e) {
    // console.error(e);
  }
  const isEmpty = decodedMessage?.trim() === "";
  const { mutate: updateMessageMutation } = useUpdateMessage();

  const handleEditMessage = (message: string) => {
    updateMessageMutation(
      {
        message: {
          id: chat.id,
          files: convertFiles(chat.files),
          sender_name: chat.sender_name ?? "AI",
          text: message,
          sender: chat.isSend ? "User" : "Machine",
          agent_id,
          session_id: chat.session ?? "",
        },
        refetch: true,
      },
      {
        onSuccess: () => {
          updateChat(chat, message);
          setEditMessage(false);
        },
        onError: () => {
          setErrorData({
            title: "Error updating messages.",
          });
        },
      },
    );
  };

  // ── HITL approval ──────────────────────────────────────────────────────────
  const isHitl = !chat.isSend && chat.properties?.hitl === true;
  const hitlActions: string[] = isHitl ? (chat.properties?.actions ?? []) : [];
  const hitlThreadId: string = isHitl ? (chat.properties?.thread_id ?? "") : "";
  const chatId = String(chat.id ?? "");
  const hitlDone = hitlDoneMap[chatId] ?? null;
  const [hitlLoading, setHitlLoading] = useState<string | null>(null);

  const handleHitlAction = async (action: string) => {
    if (hitlDone || hitlLoading) return;
    setHitlLoading(action);
    try {
      await api.post(`${getURL("HITL")}/${hitlThreadId}/resume`, {
        action,
        feedback: "",
        edited_value: "",
      });
      onHitlDone?.(chatId, action);
      // Clear the "agent running" spinner and re-fetch messages so the AI
      // response from the resumed graph appears in chat automatically.
      useMessagesStore.getState().setDisplayLoadingMessage(false);
      queryClient.invalidateQueries({ queryKey: ["useGetMessagesQuery"] });
    } catch (_err) {
      // leave buttons enabled so user can retry
    } finally {
      setHitlLoading(null);
    }
  };
  // ────────────────────────────────────────────────────────────────────────────

  const handleEvaluateAnswer = (evaluation: boolean | null) => {
    updateMessageMutation(
      {
        message: {
          ...chat,
          files: convertFiles(chat.files),
          sender_name: chat.sender_name ?? "AI",
          text: chat.message.toString(),
          sender: chat.isSend ? "User" : "Machine",
          agent_id,
          session_id: chat.session ?? "",
          properties: {
            ...chat.properties,
            positive_feedback: evaluation,
          },
        },
        refetch: true,
      },
      {
        onError: () => {
          setErrorData({
            title: "Error updating messages.",
          });
        },
      },
    );
  };

  const editedFlag = chat.edit ? (
    <div className="text-sm text-muted-foreground">(Edited)</div>
  ) : null;

  if (chat.category === "error") {
    const blocks = chat.content_blocks ?? [];

    return (
      <ErrorView
        blocks={blocks}
        showError={showError}
        lastMessage={lastMessage}
        closeChat={closeChat}
        fitViewNode={fitViewNode}
        chat={chat}
      />
    );
  }

  return (
    <>
      <div className="w-full py-2.5 word-break-break-word">
        <div
          className={cn(
            "group relative flex w-full gap-3 rounded-xl border px-3 py-2.5 transition-colors",
            chat.isSend
              ? "border-border bg-muted/35"
              : "border-border bg-background",
            !editMessage && !chat.isSend ? "hover:bg-muted/20" : "",
          )}
        >
          <div
            className={cn(
              "relative mt-0.5 flex h-[32px] w-[32px] shrink-0 items-center justify-center overflow-hidden rounded-md text-2xl",
              !chat.isSend
                ? "border border-border bg-muted"
                : "border border-border bg-background",
            )}
            style={
              chat.properties?.background_color
                ? { backgroundColor: chat.properties.background_color }
                : {}
            }
          >
            {!chat.isSend ? (
              <div className="flex h-[18px] w-[18px] items-center justify-center">
                {chat.properties?.icon ? (
                  chat.properties.icon.match(
                    /[\u2600-\u27BF\uD83C-\uDBFF\uDC00-\uDFFF]/,
                  ) ? (
                    <span className="">{chat.properties.icon}</span>
                  ) : (
                    <ForwardedIconComponent name={chat.properties.icon} />
                  )
                ) : (
                  <img
                    src={Robot}
                    className="absolute bottom-0 left-0 scale-[60%]"
                    alt={"robot_image"}
                  />
                )}
              </div>
            ) : (
              <div className="flex h-[18px] w-[18px] items-center justify-center">
                {chat.properties?.icon ? (
                  chat.properties.icon.match(
                    /[\u2600-\u27BF\uD83C-\uDBFF\uDC00-\uDFFF]/,
                  ) ? (
                    <div className="">{chat.properties.icon}</div>
                  ) : (
                    <ForwardedIconComponent name={chat.properties.icon} />
                  )
                ) : !ENABLE_AGENTCORE && !playgroundPage ? (
                  <CustomProfileIcon />
                ) : playgroundPage ? (
                  <ForwardedIconComponent name="User" />
                ) : (
                  <CustomProfileIcon />
                )}
              </div>
            )}
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            <div>
              <div
                className={cn(
                  "flex max-w-full items-baseline gap-3 truncate pb-1.5 text-sm font-semibold",
                )}
                style={
                  chat.properties?.text_color
                    ? { color: chat.properties.text_color }
                    : {}
                }
                data-testid={
                  "sender_name_" + chat.sender_name?.toLocaleLowerCase()
                }
              >
                <span className="flex items-center gap-2">
                  {chat.sender_name}
                  {isAudioMessage && (
                    <div className="flex h-5 w-5 items-center justify-center rounded-sm bg-muted">
                      <ForwardedIconComponent
                        name="mic"
                        className="h-3 w-3 text-muted-foreground"
                      />
                    </div>
                  )}
                </span>
                {chat.properties?.source && !playgroundPage && (
                  <div className="text-mmd font-normal text-muted-foreground">
                    {chat.properties?.source.source}
                  </div>
                )}
              </div>
            </div>
            {chat.content_blocks && chat.content_blocks.length > 0 && (
              <ContentBlockDisplay
                playgroundPage={playgroundPage}
                contentBlocks={chat.content_blocks}
                isLoading={
                  chat.properties?.state === "partial" &&
                  isBuilding &&
                  lastMessage
                }
                state={chat.properties?.state}
                chatId={chat.id}
              />
            )}
            {!chat.isSend ? (
              <div className="form-modal-chat-text-position flex-grow">
                <div className="form-modal-chat-text rounded-lg bg-transparent p-1">
                  {hidden && chat.thought && chat.thought !== "" && (
                    <div
                      onClick={(): void => setHidden((prev) => !prev)}
                      className="form-modal-chat-icon-div"
                    >
                      <IconComponent
                        name="MessageSquare"
                        className="form-modal-chat-icon"
                      />
                    </div>
                  )}
                  {chat.thought && chat.thought !== "" && !hidden && (
                    <SanitizedHTMLWrapper
                      className="form-modal-chat-thought"
                      content={convert.toHtml(chat.thought ?? "")}
                      onClick={() => setHidden((prev) => !prev)}
                    />
                  )}
                  {chat.thought && chat.thought !== "" && !hidden && <br></br>}
                  <div className="flex w-full flex-col">
                    <div
                      className="flex w-full flex-col dark:text-white"
                      data-testid="div-chat-message"
                    >
                      <div
                        data-testid={
                          "chat-message-" + chat.sender_name + "-" + chatMessage
                        }
                        className="flex w-full flex-col"
                      >
                        {chatMessage === "" && isBuilding && lastMessage ? (
                          <IconComponent
                            name="MoreHorizontal"
                            className="h-8 w-8 animate-pulse"
                          />
                        ) : (
                          <div className="min-h-8 w-full">
                            {editMessage ? (
                              <EditMessageField
                                key={`edit-message-${chat.id}`}
                                message={decodedMessage}
                                onEdit={(message) => {
                                  handleEditMessage(message);
                                }}
                                onCancel={() => setEditMessage(false)}
                              />
                            ) : (
                              <CustomMarkdownField
                                isAudioMessage={isAudioMessage}
                                chat={chat}
                                isEmpty={isEmpty}
                                chatMessage={chatMessage}
                                editedFlag={editedFlag}
                              />
                            )}
                            {isHitl && hitlActions.length > 0 && (
                              <div className="mt-3 flex flex-col gap-2.5">
                                <div className="flex flex-wrap gap-2">
                                {hitlActions.map((action) => {
                                  const isReject = action.toLowerCase().includes("reject");
                                  return (
                                  <button
                                    key={action}
                                    onClick={() => handleHitlAction(action)}
                                    disabled={!!hitlDone || !!hitlLoading}
                                    className={cn(
                                      "inline-flex items-center gap-1.5 rounded-md border px-4 py-1.5 text-sm font-medium transition-colors",
                                      hitlDone === action
                                        ? isReject
                                          ? "border-red-500 bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                                          : "border-green-500 bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                                        : hitlDone
                                          ? "cursor-not-allowed border-border bg-muted/30 text-muted-foreground opacity-50"
                                          : hitlLoading === action
                                            ? isReject
                                              ? "cursor-wait border-red-400 bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400"
                                              : "cursor-wait border-green-400 bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400"
                                            : hitlLoading
                                              ? "cursor-not-allowed border-border bg-muted/30 text-muted-foreground opacity-50"
                                              : isReject
                                                ? "cursor-pointer border-red-300 text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-950/30"
                                                : "cursor-pointer border-border text-foreground hover:bg-muted",
                                    )}
                                  >
                                    {hitlLoading === action
                                      ? "Submitting..."
                                      : hitlDone === action
                                        ? `✓ ${action}`
                                        : action}
                                  </button>
                                  );
                                })}
                                </div>
                                {hitlDone && (
                                  <span className="text-xs text-muted-foreground">
                                    Decision submitted — agent continued.
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="form-modal-chat-text-position flex-grow">
                <div className="flex w-full flex-col rounded-lg bg-transparent p-1">
                  {editMessage ? (
                    <EditMessageField
                      key={`edit-message-${chat.id}`}
                      message={decodedMessage}
                      onEdit={(message) => {
                        handleEditMessage(message);
                      }}
                      onCancel={() => setEditMessage(false)}
                    />
                  ) : (
                    <>
                      <div
                        className={cn(
                          "w-full items-baseline whitespace-pre-wrap break-words text-sm font-normal",
                          isEmpty ? "text-muted-foreground" : "text-primary",
                        )}
                        data-testid={`chat-message-${chat.sender_name}-${chatMessage}`}
                      >
                        {isEmpty ? EMPTY_INPUT_SEND_MESSAGE : decodedMessage}
                        {editedFlag}
                      </div>
                    </>
                  )}
                  {chat.files && (
                    <div className="my-2 flex flex-col gap-5">
                      {chat.files?.map((file, index) => {
                        return <FileCardWrapper index={index} path={file} />;
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
          {!editMessage && (
            <div className="invisible absolute -top-2 right-2 group-hover:visible">
              <div>
                <EditMessageButton
                  onCopy={() => {
                    navigator.clipboard.writeText(chatMessage);
                  }}
                  onEdit={
                    playgroundPage ? undefined : () => setEditMessage(true)
                  }
                  className="h-fit group-hover:visible"
                  isBotMessage={!chat.isSend}
                  onEvaluate={handleEvaluateAnswer}
                  evaluation={chat.properties?.positive_feedback}
                  isAudioMessage={isAudioMessage}
                />
              </div>
            </div>
          )}
        </div>
      </div>
      <div id={lastMessage ? "last-chat-message" : undefined} />
    </>
  );
}
