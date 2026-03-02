import { useCallback, useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import ThemeButtons from "@/components/core/appHeaderComponent/components/ThemeButtons";
import { useGetMessagesQuery } from "@/controllers/API/queries/messages";
import { useDeleteSession } from "@/controllers/API/queries/messages/use-delete-sessions";
import { useGetSessionsFromAgentQuery } from "@/controllers/API/queries/messages/use-get-sessions-from-agent";
import { ENABLE_PUBLISH } from "@/customization/feature-flags";
import { track } from "@/customization/utils/analytics";
import { customOpenNewTab } from "@/customization/utils/custom-open-new-tab";
import { AgentCoreButtonRedirectTarget } from "@/customization/utils/urls";
import { useUtilityStore } from "@/stores/utilityStore";
import { swatchColors } from "@/utils/styleUtils";
import AgentCoreLogoColor from "../../assets/motherson_name.svg";
import IconComponent from "../../components/common/genericIconComponent";
import { Button } from "../../components/ui/button";
import useAlertStore from "../../stores/alertStore";
import useAgentStore from "../../stores/agentStore";
import useAgentsManagerStore from "../../stores/agentsManagerStore";
import { useMessagesStore } from "../../stores/messagesStore";
import type { IOModalPropsType } from "../../types/components";
import { cn, getNumberFromString } from "../../utils/utils";
import BaseModal from "../baseModal";
import { ChatViewWrapper } from "./components/chat-view-wrapper";
import { SelectedViewField } from "./components/selected-view-field";
import { SidebarOpenView } from "./components/sidebar-open-view";
import { useGetAgentId } from "./hooks/useGetAgentId";

/* ── Gradient palette for the monogram avatar ─────────────────────── */

export default function IOModal({
  children,
  open,
  setOpen,
  disable,
  isPlayground,
  canvasOpen,
  playgroundPage,
}: IOModalPropsType): JSX.Element {
  // ─── All state & store hooks (UNCHANGED) ───────────────────────────
  const setIOModalOpen = useAgentsManagerStore((state) => state.setIOModalOpen);
  const inputs = useAgentStore((state) => state.inputs);
  const outputs = useAgentStore((state) => state.outputs);
  const nodes = useAgentStore((state) => state.nodes);
  const buildAgent = useAgentStore((state) => state.buildAgent);
  const setIsBuilding = useAgentStore((state) => state.setIsBuilding);
  const isBuilding = useAgentStore((state) => state.isBuilding);
  const newChatOnPlayground = useAgentStore(
    (state) => state.newChatOnPlayground,
  );
  const setNewChatOnPlayground = useAgentStore(
    (state) => state.setNewChatOnPlayground,
  );

  const { agentIcon, agentId, agentGradient, agentName } = useAgentStore(
    useShallow((state) => ({
      agentIcon: state.currentAgent?.icon,
      agentId: state.currentAgent?.id,
      agentGradient: state.currentAgent?.gradient,
      agentName: state.currentAgent?.name,
    })),
  );
  const filteredInputs = inputs.filter((input) => input.type !== "ChatInput");
  const chatInput = inputs.find((input) => input.type === "ChatInput");
  const filteredOutputs = outputs.filter(
    (output) => output.type !== "ChatOutput",
  );
  const chatOutput = outputs.find((output) => output.type === "ChatOutput");
  const filteredNodes = nodes.filter(
    (node) =>
      inputs.some((input) => input.id === node.id) ||
      filteredOutputs.some((output) => output.id === node.id),
  );
  const haveChat = chatInput || chatOutput;
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const deleteSession = useMessagesStore((state) => state.deleteSession);
  const currentAgentId = useGetAgentId();

  const { mutate: deleteSessionFunction } = useDeleteSession();

  const [visibleSession, setvisibleSession] = useState<string | undefined>(
    currentAgentId,
  );
  const PlaygroundTitle = playgroundPage && agentName ? agentName : "Playground";

  // ─── API queries (UNCHANGED) ───────────────────────────────────────
  const {
    data: sessionsFromDb,
    isLoading: sessionsLoading,
    refetch: refetchSessions,
  } = useGetSessionsFromAgentQuery(
    {
      id: currentAgentId,
    },
    { enabled: open },
  );

  useEffect(() => {
    if (sessionsFromDb && !sessionsLoading) {
      const sessions = [...sessionsFromDb.sessions];
      if (!sessions.includes(currentAgentId)) {
        sessions.unshift(currentAgentId);
      }
      setSessions(sessions);
    }
  }, [sessionsFromDb, sessionsLoading, currentAgentId]);

  useEffect(() => {
    setIOModalOpen(open);
    return () => {
      setIOModalOpen(false);
    };
  }, [open]);

  // ─── Session delete handler (UNCHANGED) ────────────────────────────
  function handleDeleteSession(session_id: string) {
    if (visibleSession === session_id) {
      const remainingSessions = sessions.filter((s) => s !== session_id);
      if (remainingSessions.length > 0) {
        setvisibleSession(remainingSessions[0]);
      } else {
        setvisibleSession(currentAgentId);
      }
    }

    deleteSessionFunction(
      { sessionId: session_id },
      {
        onSuccess: () => {
          deleteSession(session_id);

          const messageIdsToRemove = messages
            .filter((msg) => msg.session_id === session_id)
            .map((msg) => msg.id);

          if (messageIdsToRemove.length > 0) {
            removeMessages(messageIdsToRemove);
          }

          setSuccessData({
            title: "Session deleted successfully.",
          });
        },
        onError: () => {
          if (visibleSession !== session_id) {
            setvisibleSession(session_id);
          }

          setErrorData({
            title: "Error deleting session.",
          });
        },
      },
    );
  }

  // ─── startView helper (UNCHANGED) ─────────────────────────────────
  function startView() {
    if (!chatInput && !chatOutput) {
      if (filteredInputs.length > 0) {
        return filteredInputs[0];
      } else {
        return filteredOutputs[0];
      }
    } else {
      return undefined;
    }
  }

  const [selectedViewField, setSelectedViewField] = useState<
    { type: string; id: string } | undefined
  >(startView());

  const messages = useMessagesStore((state) => state.messages);
  const removeMessages = useMessagesStore((state) => state.removeMessages);
  const [sessions, setSessions] = useState<string[]>([]);
  const [sessionId, setSessionId] = useState<string>(currentAgentId);
  const setCurrentSessionId = useUtilityStore(
    (state) => state.setCurrentSessionId,
  );

  const { isFetched: messagesFetched, refetch: refetchMessages } =
    useGetMessagesQuery(
      {
        mode: "union",
        id: currentAgentId,
        params: {
          session_id: visibleSession,
        },
      },
      { enabled: open },
    );

  const chatValue = useUtilityStore((state) => state.chatValueStore);
  const setChatValue = useUtilityStore((state) => state.setChatValueStore);
  const eventDeliveryConfig = useUtilityStore((state) => state.eventDelivery);

  // ─── sendMessage (UNCHANGED) ──────────────────────────────────────
  const setDisplayLoadingMessage = useMessagesStore(
    (state) => state.setDisplayLoadingMessage,
  );

  const sendMessage = useCallback(
    async ({
      repeat = 1,
      files,
    }: {
      repeat: number;
      files?: string[];
    }): Promise<void> => {
      if (isBuilding) return;
      setChatValue("");
      setDisplayLoadingMessage(true);
      for (let i = 0; i < repeat; i++) {
        await buildAgent({
          input_value: chatValue,
          startNodeId: chatInput?.id,
          files: files,
          silent: true,
          session: sessionId,
          eventDelivery: eventDeliveryConfig,
        }).catch((err) => {
          console.error(err);
          throw err;
        });
      }
    },
    [isBuilding, setIsBuilding, chatValue, chatInput?.id, sessionId, buildAgent, setDisplayLoadingMessage],
  );

  // ─── Effects ─────────────────────────────────────────────────────
  useEffect(() => {
    if (playgroundPage && messages.length > 0) {
      window.sessionStorage.setItem(currentAgentId, JSON.stringify(messages));
    }
    if (newChatOnPlayground && !sessionsLoading && !isBuilding) {
      // Refetch sessions to update the sidebar list
      refetchSessions();
      // Set visible session to the current sessionId (generated when
      // "New Chat" was clicked) instead of picking the last session from
      // the DB, which may not be the newly created session due to
      // unordered results or timing issues during the build.
      if (sessionId && sessionId !== currentAgentId) {
        setvisibleSession(sessionId);
      }
      setNewChatOnPlayground(false);
    }
  }, [messages, playgroundPage, isBuilding]);

  useEffect(() => {
    if (!visibleSession) {
      setSessionId(crypto.randomUUID());
      setCurrentSessionId(currentAgentId);
    } else if (visibleSession) {
      setSessionId(visibleSession);
      setCurrentSessionId(visibleSession);
      if (selectedViewField?.type === "Session") {
        setSelectedViewField({
          id: visibleSession,
          type: "Session",
        });
      }
    }
  }, [visibleSession]);

  const setPlaygroundScrollBehaves = useUtilityStore(
    (state) => state.setPlaygroundScrollBehaves,
  );

  useEffect(() => {
    if (open) {
      setPlaygroundScrollBehaves("instant");
    }
  }, [open]);

  const showPublishOptions = playgroundPage && ENABLE_PUBLISH;

  const AgentCoreButtonClick = () => {
    track("AgentCoreButtonClick");
    customOpenNewTab(AgentCoreButtonRedirectTarget());
  };

  const swatchIndex =
    (agentGradient && !isNaN(parseInt(agentGradient))
      ? parseInt(agentGradient)
      : getNumberFromString(agentGradient ?? agentId ?? "")) %
    swatchColors.length;

  const setActiveSession = (session: string) => {
    setvisibleSession((prev) => {
      if (prev === session) {
        return undefined;
      }
      return session;
    });
  };

  const [hasInitialized, setHasInitialized] = useState(false);
  const prevVisibleSessionRef = useRef<string | undefined>(visibleSession);

  useEffect(() => {
    if (!hasInitialized) {
      setHasInitialized(true);
      prevVisibleSessionRef.current = visibleSession;
      return;
    }
    if (
      open &&
      visibleSession &&
      prevVisibleSessionRef.current !== visibleSession
    ) {
      refetchMessages();
    }

    prevVisibleSessionRef.current = visibleSession;
  }, [visibleSession]);

  // ─── Derived: monogram initial & gradient ─────────────────────────
  // ═══════════════════════════════════════════════════════════════════
  // ═══  REDESIGNED SIDEBAR (visual-only changes)  ═══════════════════
  // ═══════════════════════════════════════════════════════════════════

  const sidebarContent = (
    <div
      className={cn(
        "relative flex h-full w-full flex-col overflow-y-auto custom-scroll",
        "p-4",
        playgroundPage ? "pt-4" : "pt-3.5",
      )}
    >
      {/* ── Header: Gradient Monogram + Title ───────────────────────── */}
      <div className="mb-4 rounded-lg border border-border bg-background px-3 py-3">
        <div className="flex items-center gap-2.5">
          <div
            className={cn(
              "flex rounded-md p-1.5",
              swatchColors[swatchIndex],
            )}
          >
           
          </div>
          <div className="truncate text-sm font-semibold">{PlaygroundTitle}</div>
        </div>
      </div>

      {/* ── Sessions Section ─────────────────────────────────────────── */}
      <div className="min-h-0 flex-1">
        {/* Section label row */}
        <div className="mb-2 flex items-center justify-between px-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Conversations
          </span>
          <span className="text-xs text-muted-foreground">{sessions.length}</span>
        </div>

        {!sessionsLoading && (
          <SidebarOpenView
            sessions={sessions}
            setSelectedViewField={setSelectedViewField}
            setvisibleSession={setvisibleSession}
            handleDeleteSession={handleDeleteSession}
            visibleSession={visibleSession}
            selectedViewField={selectedViewField}
            playgroundPage={!!playgroundPage}
            setActiveSession={setActiveSession}
          />
        )}
      </div>

      {/* ── Footer / Publish Options ────────────────────────────────── */}
      {showPublishOptions && (
        <div className="mt-4 border-t border-border pt-3">
          <div className="mb-3 flex items-center justify-between px-1">
            <span className="text-sm text-muted-foreground">Theme</span>
            <ThemeButtons />
          </div>

          <Button
            onClick={AgentCoreButtonClick}
            variant="primary"
            className="w-full !rounded-lg"
          >
            <AgentCoreLogoColor />
            <span className="ml-1 text-sm">Built with AgentCore</span>
          </Button>
        </div>
      )}
    </div>
  );

  // ═══════════════════════════════════════════════════════════════════
  // ═══  RETURN  ═════════════════════════════════════════════════════
  // ═══════════════════════════════════════════════════════════════════

  return (
    <BaseModal
      open={open}
      setOpen={setOpen}
      disable={disable}
      type={isPlayground ? "full-screen" : undefined}
      onSubmit={async () => await sendMessage({ repeat: 1 })}
      size="x-large"
      className="!rounded-[12px] p-0"
    >
      <BaseModal.Trigger>{children}</BaseModal.Trigger>
      {/* TODO ADAPT TO ALL TYPES OF INPUTS AND OUTPUTS */}
      <BaseModal.Content overflowHidden className="h-full">
        {open && (
          <div className="relative flex h-full w-full bg-background">
            {/* ── Sidebar Container ─────────────────────────────────── */}
            <div
              className={cn(
                "relative flex h-full w-[280px] shrink-0 flex-col border-r border-border bg-muted/20",
              )}
            >
              {sidebarContent}
            </div>

            {/* ── Main Content (UNCHANGED) ──────────────────────────── */}
            <div className="relative flex h-full min-w-0 flex-1 flex-col bg-background">
              {selectedViewField && !sessionsLoading && (
                <SelectedViewField
                  selectedViewField={selectedViewField}
                  setSelectedViewField={setSelectedViewField}
                  haveChat={haveChat}
                  inputs={filteredInputs}
                  outputs={filteredOutputs}
                  sessions={sessions}
                  currentAgentId={currentAgentId}
                  nodes={filteredNodes}
                />
              )}
              <ChatViewWrapper
                playgroundPage={playgroundPage}
                selectedViewField={selectedViewField}
                visibleSession={visibleSession}
                sessions={sessions}
                sidebarOpen={true}
                currentAgentId={currentAgentId}
                setSidebarOpen={() => {}}
                isPlayground={isPlayground}
                setvisibleSession={setvisibleSession}
                setSelectedViewField={setSelectedViewField}
                haveChat={haveChat}
                messagesFetched={messagesFetched}
                sessionId={sessionId}
                sendMessage={sendMessage}
                canvasOpen={canvasOpen}
                setOpen={setOpen}
                playgroundTitle={PlaygroundTitle}
              />
            </div>
          </div>
        )}
      </BaseModal.Content>
    </BaseModal>
  );
}
