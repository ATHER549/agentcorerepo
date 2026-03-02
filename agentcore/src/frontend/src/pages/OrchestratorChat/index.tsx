import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Send, Sparkles, ChevronDown, Plus, MessageSquare, PanelLeftClose, PanelLeft, User, Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  useGetOrchAgents,
  useGetOrchSessions,
  useGetOrchMessages,
  useDeleteOrchSession,
} from "@/controllers/API/queries/orchestrator";
import type {
  OrchAgentSummary,
  OrchSessionSummary,
  OrchMessageResponse,
} from "@/controllers/API/queries/orchestrator";
import { performStreamingRequest } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { MarkdownField } from "@/modals/IOModal/components/chatView/chatMessage/components/edit-message";
import { ContentBlockDisplay } from "@/components/core/chatComponents/ContentBlockDisplay";
import type { ContentBlock } from "@/types/chat";

/* ------------------ TYPES ------------------ */

interface Agent {
  id: string;
  name: string;
  description: string;
  online: boolean;
  color: string;
  deploy_id: string;
  agent_id: string;
  version_number: number;
}

interface Message {
  id: string;
  sender: "user" | "agent" | "system";
  agentName?: string;
  content: string;
  timestamp: string;
  category?: string;
  contentBlocks?: ContentBlock[];
  blocksState?: string;
}

/* ------------------ COLOR PALETTE ------------------ */

const AGENT_COLORS = [
  "#10a37f", "#ab68ff", "#19c37d", "#ef4146", "#f5a623", "#0ea5e9",
  "#8b5cf6", "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16",
];

/* ------------------ HELPERS ------------------ */

function mapApiAgents(apiAgents: OrchAgentSummary[]): Agent[] {
  return apiAgents.map((a, i) => ({
    id: a.deploy_id,
    name: a.agent_name,
    description: a.agent_description || "",
    online: true,
    color: AGENT_COLORS[i % AGENT_COLORS.length],
    deploy_id: a.deploy_id,
    agent_id: a.agent_id,
    version_number: a.version_number,
  }));
}

function mapApiMessages(apiMessages: OrchMessageResponse[]): Message[] {
  return apiMessages.map((m) => ({
    id: m.id,
    sender: m.sender as "user" | "agent" | "system",
    agentName: m.sender === "agent" ? m.sender_name : undefined,
    content: m.text,
    timestamp: m.timestamp
      ? new Date(m.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : "",
    category: m.category || "message",
  }));
}

function groupSessionsByDate(
  sessions: OrchSessionSummary[],
  getLabel: (key: string) => string,
): Record<string, OrchSessionSummary[]> {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);

  const groups: Record<string, OrchSessionSummary[]> = {};

  for (const s of sessions) {
    const ts = s.last_timestamp ? new Date(s.last_timestamp) : new Date(0);
    let label: string;
    if (ts >= today) label = getLabel("Today");
    else if (ts >= yesterday) label = getLabel("Yesterday");
    else if (ts >= weekAgo) label = getLabel("Previous 7 Days");
    else label = getLabel("Older");

    if (!groups[label]) groups[label] = [];
    groups[label].push(s);
  }
  return groups;
}

/* ------------------ COMPONENT ------------------ */

export default function AgentOrchestrator() {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [showMentions, setShowMentions] = useState(false);
  const [filteredAgents, setFilteredAgents] = useState<Agent[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [selectedModel, setSelectedModel] = useState("");
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string>(crypto.randomUUID());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [streamingAgentName, setStreamingAgentName] = useState<string>("");
  const [streamingMsgId, setStreamingMsgId] = useState<string | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);

  /* ------------------ API HOOKS ------------------ */

  const { data: apiAgents } = useGetOrchAgents();
  const { data: apiSessions, refetch: refetchSessions } = useGetOrchSessions();
  const { mutate: deleteSession } = useDeleteOrchSession();

  const agents: Agent[] = useMemo(
    () => (apiAgents ? mapApiAgents(apiAgents) : []),
    [apiAgents],
  );

  // Load messages when switching to an existing session
  const { data: apiSessionMessages } = useGetOrchMessages(
    { session_id: activeSessionId || "" },
    { enabled: !!activeSessionId },
  );

  useEffect(() => {
    if (apiSessionMessages && activeSessionId) {
      setMessages(mapApiMessages(apiSessionMessages));
      setCurrentSessionId(activeSessionId);

      // Sync selectedModel with the session's active agent
      const sessionInfo = apiSessions?.find((s) => s.session_id === activeSessionId);
      if (sessionInfo?.active_agent_name) {
        setSelectedModel(sessionInfo.active_agent_name);
      }
    }
  }, [apiSessionMessages, activeSessionId, apiSessions]);

  // Set default selected model when agents load
  useEffect(() => {
    if (agents.length > 0 && !selectedModel) {
      setSelectedModel(agents[0].name);
    }
  }, [agents]);

  // Update filteredAgents when agents load
  useEffect(() => {
    setFilteredAgents(agents);
  }, [agents]);

  useEffect(() => {
    // Use instant scroll while streaming so it keeps up with fast tokens;
    // smooth scroll otherwise for a nicer UX.
    messagesEndRef.current?.scrollIntoView({
      behavior: isSending ? "auto" : "smooth",
    });
  }, [messages, isSending, streamingAgentName]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modelPickerRef.current && !modelPickerRef.current.contains(e.target as Node)) {
        setShowModelPicker(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  /* ------------------ HELPERS ------------------ */

  const timeNow = () =>
    new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const highlightMentions = (text: string) => {
    // Build a regex that matches any known @agent_name (including spaces)
    // so "@smart agent" is bolded as one unit, not just "@smart".
    if (agents.length === 0) return [text];
    const escaped = [...agents]
      .sort((a, b) => b.name.length - a.name.length)
      .map((a) => a.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp(`(@(?:${escaped.join("|")}))`, "gi");
    return text.split(pattern).map((part, i) =>
      part.startsWith("@") ? (
        <span key={i} className="font-semibold text-primary">
          {part}
        </span>
      ) : (
        part
      )
    );
  };

  const getAgentColor = (name?: string) => {
    const agent = agents.find((a) => a.name === name);
    return agent?.color || "#10a37f";
  };

  /* ------------------ INPUT HANDLING ------------------ */

  const handleInputChange = (value: string) => {
    setInput(value);
    const match = value.match(/@([\w\s]*)$/);
    if (match) {
      const query = match[1].toLowerCase();
      setFilteredAgents(agents.filter((a) => a.name.toLowerCase().includes(query)));
      setShowMentions(true);
    } else {
      setShowMentions(false);
    }
  };

  const handleSelectAgent = (agent: Agent) => {
    const updated = input.replace(/@[\w\s]*$/, `@${agent.name} `);
    setInput(updated);
    setShowMentions(false);
    textareaRef.current?.focus();
  };

  /* ------------------ SEND MESSAGE ------------------ */

  const handleSend = useCallback(async () => {
    if (!input.trim() || isSending || agents.length === 0) return;

    // Detect explicit @mention vs implicit (sticky) routing.
    // Sort by name length descending so "rag agent_new" matches before "rag agent".
    const explicitAgent = [...agents]
      .sort((a, b) => b.name.length - a.name.length)
      .find((a) => input.includes(`@${a.name}`));
    const fallbackAgent = agents.find((a) => a.name === selectedModel) || agents[0];

    // If user explicitly @mentioned an agent, update the selected model (sticky switch)
    if (explicitAgent && explicitAgent.name !== selectedModel) {
      setSelectedModel(explicitAgent.name);
    }

    // Target agent: explicit @mention wins, otherwise use sticky (selectedModel)
    const targetAgent = explicitAgent || fallbackAgent;

    // Strip the @agent_name mention so the agent only receives the actual question
    const cleanedInput = explicitAgent
      ? input.replace(new RegExp(`@${explicitAgent.name}\\s*`, "g"), "").trim()
      : input.trim();

    // Agent message placeholder — created upfront so "Thinking..." shows inside the bubble
    const agentMsgId = crypto.randomUUID();
    setStreamingMsgId(agentMsgId);

    // Add both user message AND agent "thinking" placeholder.
    // flushSync commits the DOM update synchronously, then we await a
    // double-rAF to guarantee the browser has actually painted the
    // "Thinking..." indicator before the network request begins.
    const userMessage: Message = {
      id: crypto.randomUUID(),
      sender: "user",
      content: input,
      timestamp: timeNow(),
    };
    flushSync(() => {
      setMessages((prev) => [
        ...prev,
        userMessage,
        {
          id: agentMsgId,
          sender: "agent" as const,
          agentName: targetAgent.name,
          content: "",  // empty = "Thinking..." state
          timestamp: timeNow(),
        },
      ]);
      setInput("");
      setShowMentions(false);
      setIsSending(true);
      setStreamingAgentName(targetAgent.name);
    });

    // Wait for the browser to actually paint the thinking state.
    // Double-rAF: first rAF fires before paint, second fires after paint.
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );

    let accumulated = "";
    let rafHandle: number | null = null;
    let pendingContent: string | null = null;

    // Flush the latest accumulated content to React state.
    // Called inside a rAF so we update at most once per frame (~60fps),
    // keeping the UI responsive while still showing progressive tokens.
    const flushToReact = () => {
      rafHandle = null;
      if (pendingContent === null) return;
      const content = pendingContent;
      pendingContent = null;
      flushSync(() => {
        setStreamingAgentName("");
        setMessages((prev) =>
          prev.map((m) =>
            m.id === agentMsgId ? { ...m, content } : m,
          ),
        );
      });
    };

    // Helper: update the agent message bubble content.
    // Tokens arrive very rapidly; we accumulate them and schedule
    // a single React update per animation frame to stay smooth.
    const updateAgentMsg = (content: string, immediate = false) => {
      accumulated = content;
      if (immediate) {
        // For final/error updates, flush synchronously
        if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null; }
        pendingContent = null;
        flushSync(() => {
          setStreamingAgentName("");
          setMessages((prev) =>
            prev.map((m) =>
              m.id === agentMsgId ? { ...m, content } : m,
            ),
          );
        });
        return;
      }
      pendingContent = content;
      if (rafHandle === null) {
        rafHandle = requestAnimationFrame(flushToReact);
      }
    };

    // Always send agent_id — explicit @mention or sticky selectedModel.
    // Backend sticky routing acts as fallback if agent_id is somehow missing.
    const requestBody = {
      session_id: currentSessionId,
      agent_id: targetAgent.agent_id,
      deployment_id: targetAgent.deploy_id,
      input_value: cleanedInput,
      version_number: targetAgent.version_number,
    };

    const buildController = new AbortController();

    try {
      await performStreamingRequest({
        method: "POST",
        url: `${getURL("ORCHESTRATOR")}/chat/stream`,
        body: requestBody,
        buildController,
        onData: async (event: any) => {
          const eventType: string = event?.event;
          const data: any = event?.data;

          if (eventType === "add_message" && data?.content_blocks?.length) {
            // Only show content_blocks that contain actual tool calls.
            // Each flow node (Chat Input, Worker Node, Chat Output) sends its
            // own add_message event; pipeline nodes only carry plain text steps
            // which would appear as duplicate Input/Output entries. Filtering
            // to tool_use blocks means we only show meaningful agent reasoning.
            const toolBlocks = data.content_blocks.filter((block: any) =>
              block.contents?.some((c: any) => c.type === "tool_use"),
            );
            if (toolBlocks.length > 0) {
              flushSync(() => {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === agentMsgId
                      ? {
                          ...m,
                          // Replace (not append) — each add_message is a
                          // progressive update of the same Worker Node message
                          // (Accessing → Executed), not a new block.
                          contentBlocks: toolBlocks,
                          blocksState: "partial",
                        }
                      : m,
                  ),
                );
              });
            }
          } else if (eventType === "token" && data?.chunk) {
            // Progressive streaming — append each token chunk (throttled)
            accumulated += data.chunk;
            updateAgentMsg(accumulated);
          } else if (eventType === "error") {
            updateAgentMsg(data?.text || "An error occurred", true);
            return false;
          } else if (eventType === "end") {
            // End event carries the final complete text — flush immediately
            if (data?.agent_text) {
              updateAgentMsg(data.agent_text, true);
            }
            // Mark content blocks as fully finished
            setMessages((prev) =>
              prev.map((m) =>
                m.id === agentMsgId && m.contentBlocks?.length
                  ? { ...m, blocksState: "complete" }
                  : m,
              ),
            );
            refetchSessions();
            return false;
          }
          return true;
        },
        onError: (statusCode) => {
          updateAgentMsg(`Error: server returned ${statusCode}`, true);
        },
        onNetworkError: (error) => {
          if (error.name !== "AbortError") {
            updateAgentMsg("Sorry, something went wrong. Please try again.", true);
          }
        },
      });
    } catch {
      if (!accumulated) {
        updateAgentMsg("Sorry, something went wrong. Please try again.", true);
      }
    } finally {
      // Flush any remaining buffered content and clean up
      if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null; }
      if (pendingContent !== null) {
        const finalContent = pendingContent;
        pendingContent = null;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === agentMsgId ? { ...m, content: finalContent } : m,
          ),
        );
      }
      setIsSending(false);
      setStreamingAgentName("");
      setStreamingMsgId(null);
    }
  }, [input, isSending, agents, selectedModel, currentSessionId, refetchSessions]);

  /* ------------------ SESSION MANAGEMENT ------------------ */

  const handleNewChat = () => {
    setCurrentSessionId(crypto.randomUUID());
    setActiveSessionId(null);
    setMessages([]);
  };

  const handleSelectSession = (sessionId: string) => {
    setActiveSessionId(sessionId);
  };

  const handleDeleteSession = (sessionId: string) => {
    deleteSession(
      { session_id: sessionId },
      {
        onSuccess: () => {
          if (currentSessionId === sessionId) {
            handleNewChat();
          }
          refetchSessions();
        },
      },
    );
  };

  /* ---- group chat history by date ---- */
  const grouped = useMemo(
    () => groupSessionsByDate(apiSessions || [], t),
    [apiSessions, t],
  );

  /* ------------------ RENDER ------------------ */

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      {/* ================ SIDEBAR ================ */}
      <div
        className={`flex flex-col overflow-hidden border-r border-border bg-muted transition-all duration-200 ${
          sidebarOpen ? "w-64 min-w-[16rem]" : "w-0 min-w-0"
        }`}
      >
        {/* Sidebar Header */}
        <div className="flex items-center justify-between p-3">
          <button
            onClick={() => setSidebarOpen(false)}
            className="flex items-center rounded-md p-1.5 text-muted-foreground hover:bg-accent"
          >
            <PanelLeftClose size={18} />
          </button>
          <button
            onClick={handleNewChat}
            className="flex items-center rounded-md p-1.5 text-muted-foreground hover:bg-accent"
          >
            <Plus size={18} />
          </button>
        </div>

        {/* Chat History */}
        <div className="flex-1 overflow-y-auto px-2">
          {Object.entries(grouped).map(([date, chats]) => (
            <div key={date} className="mb-4">
              <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {date}
              </div>
              {chats.map((chat) => (
                <div
                  key={chat.session_id}
                  className="group relative flex items-center"
                >
                  <button
                    onClick={() => handleSelectSession(chat.session_id)}
                    className={`flex min-w-0 flex-1 items-center gap-2 truncate rounded-lg px-2 py-2.5 pr-8 text-left text-sm text-foreground hover:bg-accent ${
                      currentSessionId === chat.session_id ? "bg-accent" : ""
                    }`}
                  >
                    <MessageSquare size={14} className="shrink-0 opacity-50" />
                    <span className="truncate">{chat.preview || t("New conversation")}</span>
                  </button>
                  {/* Delete button — visible on hover */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteSession(chat.session_id);
                    }}
                    className="invisible absolute right-1 shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-red-500 group-hover:visible"
                    title={t("Delete session")}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* Agents Panel */}
        <div className="border-t border-border px-2 py-3">
          <div className="px-2 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("Agents")}
          </div>
          <div className="flex flex-col gap-0.5">
            {agents.map((agent) => (
              <button
                key={agent.id}
                onClick={() => {
                  setSelectedModel(agent.name);
                  setShowModelPicker(false);
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] text-foreground hover:bg-accent ${
                  selectedModel === agent.name ? "bg-accent" : ""
                }`}
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: agent.online ? agent.color : undefined }}
                />
                <span className="truncate">{agent.name}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ================ MAIN AREA ================ */}
      <div className="relative flex flex-1 flex-col">
        {/* Top Bar */}
        <div className="flex h-[52px] shrink-0 items-center gap-2 border-b border-border px-4">
          {!sidebarOpen && (
            <button
              onClick={() => setSidebarOpen(true)}
              className="flex items-center rounded-md p-1.5 text-muted-foreground hover:bg-accent"
            >
              <PanelLeft size={18} />
            </button>
          )}

          {/* Model selector */}
          <div ref={modelPickerRef} className="relative">
            <button
              onClick={() => setShowModelPicker(!showModelPicker)}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[15px] font-semibold text-foreground hover:bg-accent"
            >
              <Sparkles size={16} style={{ color: getAgentColor(selectedModel) }} />
              {selectedModel || t("Select Agent")}
              <ChevronDown size={14} className="opacity-50" />
            </button>

            {showModelPicker && (
              <div className="absolute left-0 top-full z-50 mt-1 min-w-[240px] rounded-xl border border-border bg-popover p-1 shadow-lg">
                {agents.map((agent) => (
                  <button
                    key={agent.id}
                    onClick={() => {
                      setSelectedModel(agent.name);
                      setShowModelPicker(false);
                    }}
                    className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent ${
                      selectedModel === agent.name ? "bg-accent" : ""
                    }`}
                  >
                    <span
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                      style={{ background: agent.color }}
                    >
                      <Sparkles size={14} color="white" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">{agent.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {agent.description}
                      </div>
                    </div>
                    {selectedModel === agent.name && (
                      <span className="ml-auto text-primary">✓</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ================ MESSAGES ================ */}
        <div className="flex flex-1 flex-col items-center overflow-y-auto">
          <div className="w-full max-w-3xl px-6 pb-44 pt-6">
            {messages.map((msg) => {
              // Context reset divider
              if (msg.category === "context_reset") {
                return (
                  <div key={msg.id} className="flex items-center gap-3 py-4">
                    <div className="h-px flex-1 bg-border" />
                    <span className="text-xs font-medium text-muted-foreground">
                      {msg.content}
                    </span>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                );
              }

              const isUser = msg.sender === "user";
              const isThinking = msg.sender === "agent" && msg.content === "" && isSending;
              return (
                <div key={msg.id} className="flex items-start gap-4 py-5">
                  {/* Avatar */}
                  <div
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center ${
                      isUser ? "rounded-full bg-muted" : "rounded-lg"
                    }`}
                    style={!isUser ? { background: getAgentColor(msg.agentName) } : undefined}
                  >
                    {isUser ? (
                      <User size={16} className="text-muted-foreground" />
                    ) : (
                      <Sparkles size={16} color="white" />
                    )}
                  </div>

                  {/* Content */}
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-foreground">
                      {isUser ? t("You") : msg.agentName}
                      <span className="text-xs font-normal text-muted-foreground">
                        {msg.timestamp}
                      </span>
                    </div>
                    {isThinking ? (
                      <div className="flex items-center gap-2">
                        <Loader2 size={16} className="animate-spin text-muted-foreground" />
                        <span className="text-sm text-muted-foreground">{t("Thinking...")}</span>
                      </div>
                    ) : isUser ? (
                      <div className="text-[15px] leading-relaxed text-foreground/80">
                        {highlightMentions(msg.content)}
                      </div>
                    ) : (
                      <div className="text-[15px] leading-relaxed text-foreground/80">
                        {msg.contentBlocks && msg.contentBlocks.length > 0 && (
                          <ContentBlockDisplay
                            contentBlocks={msg.contentBlocks}
                            chatId={msg.id}
                            state={msg.blocksState}
                            isLoading={isSending && msg.id === streamingMsgId}
                          />
                        )}
                        <MarkdownField
                          chat={{}}
                          isEmpty={!msg.content}
                          chatMessage={msg.content}
                          editedFlag={null}
                        />
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* ================ INPUT AREA ================ */}
        <div className="pointer-events-none absolute bottom-0 left-0 right-0 flex justify-center bg-gradient-to-t from-background from-40% to-transparent px-6 pb-6">
          <div className="pointer-events-auto relative w-full max-w-3xl">
            {/* Mention dropdown */}
            {showMentions && (
              <div className="absolute bottom-full left-0 z-50 mb-2 max-h-64 min-w-[240px] overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-lg">
                {filteredAgents.map((agent) => (
                  <button
                    key={agent.id}
                    onClick={() => handleSelectAgent(agent)}
                    className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm text-foreground hover:bg-accent"
                  >
                    <span
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
                      style={{ background: agent.color }}
                    >
                      <Sparkles size={12} color="white" />
                    </span>
                    <div className="min-w-0">
                      <div className="font-medium">@{agent.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {agent.description}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Text Input */}
            <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => handleInputChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder={t("Message agents or type @ to mention...")}
                rows={1}
                className="w-full resize-none border-none bg-transparent px-5 py-4 pr-14 text-[15px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0"
              />
              <div className="flex items-center justify-end px-3 pb-3">
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || isSending}
                  className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
                    input.trim() && !isSending
                      ? "bg-foreground text-background hover:opacity-90"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  <Send size={16} className="-ml-px -mt-px" />
                </button>
              </div>
            </div>

            <div className="mt-2 text-center text-xs text-muted-foreground">
              {t("Agents can make mistakes. Review important info.")}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
