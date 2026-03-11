import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import {
  Activity, Clock, Layers, DollarSign, Timer, Bot, FolderOpen,
  ChevronRight, AlertCircle,
} from "lucide-react";
import { THEME } from "../theme";
import { formatCost, formatTokens, formatLatency, formatDate } from "../utils";
import type {
  SessionDetailResponse, TraceDetailResponse,
  AgentDetailResponse, ProjectDetailResponse,
} from "../types";

interface SessionDetailDialogProps {
  selectedSession: string | null;
  onClose: () => void;
  sessionDetail: SessionDetailResponse | undefined;
  isLoading: boolean;
  isFetching: boolean;
  onSelectTrace: (id: string) => void;
}

export function SessionDetailDialog({ selectedSession, onClose, sessionDetail, isLoading, isFetching, onSelectTrace }: SessionDetailDialogProps) {
  return (
    <Dialog open={!!selectedSession} onOpenChange={() => onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
            <Clock className="h-5 w-5" style={{ color: THEME.primary }} />
            Session Details
          </DialogTitle>
          <DialogDescription className="truncate" style={{ color: THEME.textSecondary }}>{selectedSession}</DialogDescription>
        </DialogHeader>
        {isLoading || isFetching ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-gray-200" style={{ borderTopColor: THEME.primary }} />
            <p className="text-sm" style={{ color: THEME.textSecondary }}>Loading session details...</p>
          </div>
        ) : sessionDetail ? (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: "Traces", value: sessionDetail.trace_count, icon: Activity },
                { label: "Tokens", value: formatTokens(sessionDetail.total_tokens), icon: Layers },
                { label: "Cost", value: formatCost(sessionDetail.total_cost), icon: DollarSign },
                { label: "Duration", value: sessionDetail.first_trace_at && sessionDetail.last_trace_at
                  ? `${Math.round((new Date(sessionDetail.last_trace_at).getTime() - new Date(sessionDetail.first_trace_at).getTime()) / 1000)}s`
                  : "-", icon: Timer },
              ].map((stat, idx) => (
                <div key={idx} className="bg-gray-50 p-4 rounded-lg">
                  <div className="flex items-center gap-2 mb-1">
                    <stat.icon className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                    <p className="text-sm" style={{ color: THEME.textSecondary }}>{stat.label}</p>
                  </div>
                  <p className="text-xl font-bold" style={{ color: THEME.textMain }}>{stat.value}</p>
                </div>
              ))}
            </div>
            <div>
              <h4 className="font-medium mb-3" style={{ color: THEME.textMain }}>Traces</h4>
              <div className="space-y-2">
                {sessionDetail.traces.map((trace) => (
                  <div key={trace.id} className="p-4 bg-gray-50 rounded-lg cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => onSelectTrace(trace.id)}>
                    <div className="flex justify-between items-center">
                      <div>
                        <p className="font-medium" style={{ color: THEME.textMain }}>{trace.name || trace.id}</p>
                        <p className="text-sm" style={{ color: THEME.textSecondary }}>{formatDate(trace.timestamp)} | {formatTokens(trace.total_tokens)} tokens | {formatCost(trace.total_cost)}</p>
                      </div>
                      <ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

interface TraceDetailDialogProps {
  selectedTrace: string | null;
  onClose: () => void;
  traceDetail: TraceDetailResponse | undefined;
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
}

export function TraceDetailDialog({ selectedTrace, onClose, traceDetail, isLoading, isFetching, isError }: TraceDetailDialogProps) {
  const [expandedObs, setExpandedObs] = useState<string | null>(null);

  return (
    <Dialog open={!!selectedTrace} onOpenChange={() => onClose()}>
      <DialogContent className="max-w-4xl max-h-[80vh] overflow-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
            <Activity className="h-5 w-5" style={{ color: THEME.primary }} />
            Trace Details
          </DialogTitle>
          <DialogDescription style={{ color: THEME.textSecondary }}>{traceDetail?.name || selectedTrace}</DialogDescription>
        </DialogHeader>
        {isLoading || isFetching ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-gray-200" style={{ borderTopColor: THEME.primary }} />
            <p className="text-sm" style={{ color: THEME.textSecondary }}>Loading trace details...</p>
          </div>
        ) : traceDetail ? (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: "Input Tokens", value: formatTokens(traceDetail.input_tokens), icon: Layers },
                { label: "Output Tokens", value: formatTokens(traceDetail.output_tokens), icon: Layers },
                { label: "Cost", value: formatCost(traceDetail.total_cost), icon: DollarSign },
                { label: "Latency", value: formatLatency(traceDetail.latency_ms), icon: Timer },
              ].map((stat, idx) => (
                <div key={idx} className="bg-gray-50 p-4 rounded-lg">
                  <div className="flex items-center gap-2 mb-1">
                    <stat.icon className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                    <p className="text-sm" style={{ color: THEME.textSecondary }}>{stat.label}</p>
                  </div>
                  <p className="text-xl font-bold" style={{ color: THEME.textMain }}>{stat.value}</p>
                </div>
              ))}
            </div>

            <div>
              <h4 className="font-medium mb-3" style={{ color: THEME.textMain }}>Evaluation Scores</h4>
              {!traceDetail.scores || traceDetail.scores.length === 0 ? (
                <div className="text-sm bg-gray-50 rounded-lg p-4" style={{ color: THEME.textSecondary }}>No evaluation scores found for this trace.</div>
              ) : (
                <div className="space-y-2">
                  {traceDetail.scores.map((score) => (
                    <div key={score.id} className="bg-gray-50 rounded-lg p-4 border border-gray-100">
                      <div className="flex justify-between items-center gap-4">
                        <div className="min-w-0">
                          <p className="font-medium truncate" style={{ color: THEME.textMain }}>{score.name}</p>
                          <p className="text-xs" style={{ color: THEME.textSecondary }}>{score.source || "evaluator"}{score.created_at ? ` | ${formatDate(score.created_at)}` : ""}</p>
                        </div>
                        <Badge variant="outline" className="font-semibold">{Number.isFinite(score.value) ? score.value.toFixed(3) : score.value}</Badge>
                      </div>
                      {score.comment && <p className="text-sm mt-2 whitespace-pre-wrap" style={{ color: THEME.textSecondary }}>{score.comment}</p>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <h4 className="font-medium mb-3" style={{ color: THEME.textMain }}>Observations Timeline</h4>
              {traceDetail.observations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 bg-gray-50 rounded-lg gap-2">
                  <Layers className="h-8 w-8 text-gray-300" />
                  <p className="text-sm" style={{ color: THEME.textSecondary }}>No observations found for this trace.</p>
                  <p className="text-xs" style={{ color: THEME.textSecondary }}>The trace may still be processing, or observations were not recorded.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {traceDetail.observations.map((obs) => (
                    <div
                      key={obs.id}
                      className={`p-4 rounded-lg border cursor-pointer transition-colors ${obs.level === "ERROR" ? "border-red-200 bg-red-50" : "bg-gray-50 hover:bg-gray-100 border-gray-100"}`}
                      onClick={() => setExpandedObs(expandedObs === obs.id ? null : obs.id)}
                    >
                      <div className="flex justify-between items-center">
                        <div className="flex items-center gap-2">
                          <Badge style={{ backgroundColor: obs.type === "GENERATION" ? THEME.primary : '#e5e7eb', color: obs.type === "GENERATION" ? 'white' : THEME.textMain }}>{obs.type || "SPAN"}</Badge>
                          <span className="font-medium" style={{ color: THEME.textMain }}>{obs.name || "Unnamed"}</span>
                          {obs.model && <Badge variant="outline" className="text-xs">{obs.model.split("/").pop() || obs.model}</Badge>}
                        </div>
                        <div className="text-sm" style={{ color: THEME.textSecondary }}>{formatTokens(obs.total_tokens)} tokens | {formatCost(obs.total_cost)} | {formatLatency(obs.latency_ms)}</div>
                      </div>
                      {expandedObs === obs.id && (
                        <div className="mt-3 pt-3 border-t border-gray-200 space-y-2">
                          {Boolean(obs.input) && (
                            <div>
                              <p className="text-sm font-medium mb-1" style={{ color: THEME.textMain }}>Input</p>
                              <pre className="text-xs bg-white p-3 rounded border overflow-auto max-h-32" style={{ color: THEME.textSecondary }}>{JSON.stringify(obs.input, null, 2)}</pre>
                            </div>
                          )}
                          {Boolean(obs.output) && (
                            <div>
                              <p className="text-sm font-medium mb-1" style={{ color: THEME.textMain }}>Output</p>
                              <pre className="text-xs bg-white p-3 rounded border overflow-auto max-h-32" style={{ color: THEME.textSecondary }}>{JSON.stringify(obs.output, null, 2)}</pre>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <AlertCircle className="h-10 w-10" style={{ color: THEME.error }} />
            <p className="text-sm font-semibold" style={{ color: THEME.textMain }}>Trace could not be loaded</p>
            <p className="text-xs text-center max-w-xs" style={{ color: THEME.textSecondary }}>The trace may have been deleted, or is not accessible in the current time range. Try widening the date filter.</p>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

interface AgentDetailDialogProps {
  selectedAgent: string | null;
  onClose: () => void;
  agentDetail: AgentDetailResponse | undefined;
  isLoading: boolean;
  onSelectSession: (id: string) => void;
}

export function AgentDetailDialog({ selectedAgent, onClose, agentDetail, isLoading, onSelectSession }: AgentDetailDialogProps) {
  return (
    <Dialog open={!!selectedAgent} onOpenChange={() => onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
            <Bot className="h-5 w-5" style={{ color: THEME.primary }} />
            {agentDetail?.agent_name || "Agent Details"}
          </DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-gray-200" style={{ borderTopColor: THEME.primary }} />
            <p className="text-sm" style={{ color: THEME.textSecondary }}>Loading agent details...</p>
          </div>
        ) : agentDetail ? (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: "Traces", value: agentDetail.trace_count, icon: Activity },
                { label: "Sessions", value: agentDetail.session_count, icon: Clock },
                { label: "Tokens", value: formatTokens(agentDetail.total_tokens), icon: Layers },
                { label: "Cost", value: formatCost(agentDetail.total_cost), icon: DollarSign },
              ].map((stat, idx) => (
                <div key={idx} className="bg-gray-50 p-4 rounded-lg">
                  <div className="flex items-center gap-2 mb-1">
                    <stat.icon className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                    <p className="text-sm" style={{ color: THEME.textSecondary }}>{stat.label}</p>
                  </div>
                  <p className="text-xl font-bold" style={{ color: THEME.textMain }}>{stat.value}</p>
                </div>
              ))}
            </div>
            <div>
              <h4 className="font-medium mb-3" style={{ color: THEME.textMain }}>Sessions</h4>
              <div className="space-y-2">
                {agentDetail.sessions.map((session) => (
                  <div
                    key={session.session_id}
                    className={`p-4 rounded-lg cursor-pointer transition-colors ${session.has_errors ? "bg-red-50 border border-red-200" : "bg-gray-50 hover:bg-gray-100"}`}
                    onClick={() => { onClose(); onSelectSession(session.session_id); }}
                  >
                    <div className="flex justify-between items-center">
                      <div>
                        <p className="font-medium truncate max-w-[300px]" style={{ color: THEME.textMain }}>{session.session_id}</p>
                        <p className="text-sm" style={{ color: THEME.textSecondary }}>{session.trace_count} traces | {formatTokens(session.total_tokens)} tokens | {formatCost(session.total_cost)}</p>
                      </div>
                      <ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

interface ProjectDetailDialogProps {
  selectedProject: string | null;
  onClose: () => void;
  projectDetail: ProjectDetailResponse | undefined;
  isLoading: boolean;
  onSelectAgent: (id: string) => void;
}

export function ProjectDetailDialog({ selectedProject, onClose, projectDetail, isLoading, onSelectAgent }: ProjectDetailDialogProps) {
  return (
    <Dialog open={!!selectedProject} onOpenChange={() => onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
            <FolderOpen className="h-5 w-5" style={{ color: THEME.chartColors[3] }} />
            {projectDetail?.project_name || "Project Details"}
          </DialogTitle>
          <DialogDescription style={{ color: THEME.textSecondary }}>
            {isLoading && !projectDetail ? "Loading..." : `${projectDetail?.agent_count ?? 0} agents`}
          </DialogDescription>
        </DialogHeader>
        {projectDetail && (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: "Agents", value: projectDetail.agent_count, icon: Bot },
                { label: "Traces", value: projectDetail.trace_count, icon: Activity },
                { label: "Tokens", value: formatTokens(projectDetail.total_tokens), icon: Layers },
                { label: "Cost", value: formatCost(projectDetail.total_cost), icon: DollarSign },
              ].map((stat, idx) => (
                <div key={idx} className="bg-gray-50 p-4 rounded-lg">
                  <div className="flex items-center gap-2 mb-1">
                    <stat.icon className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                    <p className="text-sm" style={{ color: THEME.textSecondary }}>{stat.label}</p>
                  </div>
                  <p className="text-xl font-bold" style={{ color: THEME.textMain }}>{stat.value}</p>
                </div>
              ))}
            </div>
            <div>
              <h4 className="font-medium mb-3" style={{ color: THEME.textMain }}>Agents</h4>
              <div className="space-y-2">
                {projectDetail.agents.map((agent) => (
                  <div key={agent.agent_id} className="p-4 bg-gray-50 rounded-lg cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => { onClose(); onSelectAgent(agent.agent_id); }}>
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${THEME.primary}10` }}>
                          <Bot className="h-4 w-4" style={{ color: THEME.primary }} />
                        </div>
                        <div>
                          <p className="font-medium" style={{ color: THEME.textMain }}>{agent.agent_name}</p>
                          <p className="text-sm" style={{ color: THEME.textSecondary }}>{agent.trace_count} traces | {agent.session_count} sessions | {formatTokens(agent.total_tokens)} tokens</p>
                        </div>
                      </div>
                      <ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
