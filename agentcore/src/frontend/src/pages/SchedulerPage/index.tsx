import React from "react";
import {
  Zap,
  Plus,
  Play,
  Pencil,
  Trash2,
  List,
  Loader2,
  Clock,
  FolderSearch,
  ChevronRight,
  X,
  CheckCircle2,
  XCircle,
  RefreshCw,
} from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { useEffect, useMemo, useState } from "react";
import Loading from "@/components/ui/loading";
import {
  useGetConnectorCatalogue,
} from "@/controllers/API/queries/connectors/use-get-connector-catalogue";
import { useGetControlPanelAgents } from "@/controllers/API/queries/control-panel";
import {
  useGetAllTriggers,
  type TriggerInfo,
} from "@/controllers/API/queries/triggers/use-get-all-triggers";
import {
  useCreateTrigger,
  useUpdateTrigger,
  useToggleTrigger,
  useDeleteTrigger,
  useRunTriggerNow,
  useGetTriggerLogs,
  type CreateTriggerPayload,
  type TriggerExecutionLog,
} from "@/controllers/API/queries/triggers/use-mutate-trigger";

// ── Types ─────────────────────────────────────────────────────────────────

type TriggerTypeFilter = "all" | "schedule";

interface AgentOption {
  deployId: string;       // deploy_id — unique per deployment
  agentId: string;        // agent_id — may repeat across versions
  name: string;
  environment: "uat" | "prod";
  version: string;        // e.g. "v1", "v2"
  isActive: boolean;      // Start/Stop from control panel
  isEnabled: boolean;     // Enable/Disable from control panel
  inputType: "chat" | "autonomous" | "file_processing";
}

// ── Helpers ───────────────────────────────────────────────────────────────

function formatSchedule(trigger: TriggerInfo): string {
  const cfg = trigger.trigger_config ?? {};
  if (trigger.trigger_type === "schedule") {
    if (cfg.schedule_type === "cron") {
      return parseCron(cfg.cron_expression ?? "");
    }
    const mins = cfg.interval_minutes ?? 60;
    if (mins < 60) return `Every ${mins} min`;
    if (mins % 1440 === 0) return `Every ${mins / 1440} day(s)`;
    if (mins % 60 === 0) return `Every ${mins / 60} hr`;
    return `Every ${mins} min`;
  }
  if (trigger.trigger_type === "folder_monitor") {
    const st = cfg.storage_type ?? "";
    const poll = cfg.poll_interval_seconds ?? 30;
    const pollLabel = poll >= 60 ? `${Math.round(poll / 60)}m` : `${poll}s`;
    if (st === "Azure Blob Storage") return `Azure — poll ${pollLabel}`;
    if (st === "SharePoint") {
      return `SharePoint — poll ${pollLabel}`;
    }
  }
  return "—";
}

function parseCron(expr: string): string {
  if (!expr) return "Custom cron";
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, dom, , dow] = parts;
  if (dom === "*" && dow === "*") {
    if (hour !== "*" && min !== "*") return `Daily at ${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;
  }
  if (dom === "*" && dow !== "*") {
    if (hour !== "*" && min !== "*") return `Weekdays at ${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;
  }
  return expr;
}

function formatLastRun(ts: string | null): string {
  if (!ts) return "Never";
  const diff = Date.now() - new Date(ts).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function envBadge(env: string): JSX.Element {
  const styles: Record<string, string> = {
    prod: "bg-green-100 text-green-800",
    uat: "bg-yellow-100 text-yellow-800",
    dev: "bg-slate-100 text-slate-600",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${styles[env] ?? styles.dev}`}>
      {env}
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────

export default function SchedulerPage(): JSX.Element {
  const [typeFilter, setTypeFilter] = useState<TriggerTypeFilter>("all");
  const [showModal, setShowModal] = useState(false);
  const [logsTriggerId, setLogsTriggerId] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [editingTrigger, setEditingTrigger] = useState<TriggerInfo | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);

  const { data: triggers = [], isLoading } = useGetAllTriggers({
    triggerType: typeFilter !== "all" ? typeFilter : undefined,
  });

  // Fetch deployment statuses to know which are stopped/disabled in control panel
  const { data: uatStatusData } = useGetControlPanelAgents(
    { env: "uat", page: 1, size: 100 },
    { refetchOnWindowFocus: false, refetchInterval: 30_000 },
  );
  const { data: prodStatusData } = useGetControlPanelAgents(
    { env: "prod", page: 1, size: 100 },
    { refetchOnWindowFocus: false, refetchInterval: 30_000 },
  );
  // Map deploy_id → { isActive, isEnabled }
  const deploymentStatusMap = useMemo(() => {
    const map = new Map<string, { isActive: boolean; isEnabled: boolean }>();
    for (const item of uatStatusData?.items ?? []) {
      map.set(item.deploy_id, { isActive: item.is_active, isEnabled: item.is_enabled });
    }
    for (const item of prodStatusData?.items ?? []) {
      map.set(item.deploy_id, { isActive: item.is_active, isEnabled: item.is_enabled });
    }
    return map;
  }, [uatStatusData, prodStatusData]);

  const toggleMutation = useToggleTrigger();
  const deleteMutation = useDeleteTrigger();
  const runNowMutation = useRunTriggerNow();

  const handleToggle = (id: string) => toggleMutation.mutate(id);

  const handleDelete = async (id: string) => {
    await deleteMutation.mutateAsync(id);
    setDeleteConfirm(null);
  };

  const handleRunNow = async (id: string) => {
    setRunningId(id);
    setLogsTriggerId(id); // auto-open logs so user sees Running → Success
    try {
      await runNowMutation.mutateAsync(id);
    } finally {
      setRunningId(null);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Agent Scheduler</h1>
          <p className="text-sm text-muted-foreground">
            Schedule and monitor autonomous agent runs for published agents
          </p>
        </div>
        <button
          onClick={() => { setEditingTrigger(null); setShowModal(true); }}
          className="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors bg-[var(--button-primary)] text-[var(--button-primary-foreground)] hover:bg-[var(--button-primary-hover)]"
        >
          <Plus className="h-4 w-4" />
          Add Scheduler
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 border-b border-border px-6 pt-3">
        {(["all", "schedule"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTypeFilter(t)}
            className={`flex items-center gap-1.5 rounded-t-md px-4 py-2 text-sm font-medium transition-colors ${
              typeFilter === t
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t === "all" && <Zap className="h-3.5 w-3.5" />}
            {t === "schedule" && <Clock className="h-3.5 w-3.5" />}
            {t === "all" ? "All" : "Schedule"}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {isLoading ? (
          <div className="flex h-40 items-center justify-center">
            <Loading />
          </div>
        ) : triggers.length === 0 ? (
          <EmptyState onAdd={() => { setEditingTrigger(null); setShowModal(true); }} />
        ) : (
          <TriggersTable
            triggers={triggers}
            runningId={runningId}
            deploymentStatusMap={deploymentStatusMap}
            onToggle={handleToggle}
            onRunNow={handleRunNow}
            onEdit={(t) => { setEditingTrigger(t); setShowModal(true); }}
            onLogs={(id) => setLogsTriggerId(id)}
            onDelete={(id) => setDeleteConfirm(id)}
          />
        )}
      </div>

      {/* Add/Edit Scheduler Modal */}
      {showModal && (
        <AddSchedulerModal
          editing={editingTrigger}
          onClose={() => setShowModal(false)}
        />
      )}

      {/* Logs slide-over */}
      {logsTriggerId && (
        <LogsSlideOver
          triggerId={logsTriggerId}
          triggerName={
            triggers.find((t) => t.id === logsTriggerId)?.agent_name ?? "Trigger"
          }
          onClose={() => setLogsTriggerId(null)}
        />
      )}

      {/* Delete confirm */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-80 rounded-lg bg-background p-6 shadow-xl">
            <h3 className="mb-2 font-semibold text-foreground">Delete Scheduler</h3>
            <p className="mb-4 text-sm text-muted-foreground">
              This will permanently remove the trigger and stop all scheduled runs.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={deleteMutation.isPending}
                className="flex items-center gap-1 rounded-md bg-destructive px-3 py-1.5 text-sm text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
              >
                {deleteMutation.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── EmptyState ────────────────────────────────────────────────────────────

function EmptyState({ onAdd }: { onAdd: () => void }): JSX.Element {
  return (
    <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
      <div className="rounded-full bg-muted p-4">
        <Zap className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <p className="font-medium text-foreground">No schedulers yet</p>
        <p className="text-sm text-muted-foreground">
          Add your first scheduler to start running agents on a schedule or trigger.
        </p>
      </div>
      <button
        onClick={onAdd}
        className="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors bg-[var(--button-primary)] text-[var(--button-primary-foreground)] hover:bg-[var(--button-primary-hover)]"
      >
        <Plus className="h-4 w-4" />
        Add Scheduler
      </button>
    </div>
  );
}

// ── TriggersTable ─────────────────────────────────────────────────────────

interface TableProps {
  triggers: TriggerInfo[];
  runningId: string | null;
  deploymentStatusMap: Map<string, { isActive: boolean; isEnabled: boolean }>;
  onToggle: (id: string) => void;
  onRunNow: (id: string) => void;
  onEdit: (t: TriggerInfo) => void;
  onLogs: (id: string) => void;
  onDelete: (id: string) => void;
}

function TriggersTable({
  triggers,
  runningId,
  deploymentStatusMap,
  onToggle,
  onRunNow,
  onEdit,
  onLogs,
  onDelete,
}: TableProps): JSX.Element {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-background">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-4 py-3 text-left">Status</th>
            <th className="px-4 py-3 text-left">Agent</th>
            <th className="px-4 py-3 text-left">Type</th>
            <th className="px-4 py-3 text-left">Schedule / Source</th>
            <th className="px-4 py-3 text-left">Env</th>
            <th className="px-4 py-3 text-right">Runs</th>
            <th className="px-4 py-3 text-left">Last Run</th>
            <th className="px-4 py-3 text-left">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {triggers.map((t) => {
            // Check if the linked deployment is stopped or disabled in the control panel
            const deplStatus = t.deployment_id
              ? deploymentStatusMap.get(t.deployment_id)
              : undefined;
            // deplStatus undefined means deployment not yet loaded — don't block
            const deploymentStopped =
              deplStatus !== undefined && (!deplStatus.isActive || !deplStatus.isEnabled);

            return (
            <tr
              key={t.id}
              className={`hover:bg-muted/30 ${deploymentStopped ? "opacity-50" : ""}`}
            >
              {/* Active toggle */}
              <td className="px-4 py-3">
                <div className="flex flex-col items-start gap-1">
                  <Switch
                    checked={t.is_active}
                    onCheckedChange={() => onToggle(t.id)}
                    disabled={deploymentStopped}
                  />
                  <span
                    className={`text-[10px] font-medium leading-none ${
                      deploymentStopped
                        ? "text-destructive"
                        : t.is_active ? "text-green-600" : "text-muted-foreground"
                    }`}
                  >
                    {deploymentStopped ? "Stopped" : t.is_active ? "Active" : "Paused"}
                  </span>
                </div>
              </td>

              {/* Agent name + version */}
              <td className="px-4 py-3">
                <span className="font-medium">{t.agent_name}</span>
                {t.version && (
                  <span className="ml-1.5 text-xs text-muted-foreground">
                    {String(t.version).startsWith("v") ? t.version : `v${t.version}`}
                  </span>
                )}
              </td>

              {/* Type */}
              <td className="px-4 py-3">
                <span className="flex items-center gap-1 capitalize text-muted-foreground">
                  {t.trigger_type === "schedule" ? (
                    <Clock className="h-3.5 w-3.5" />
                  ) : (
                    <FolderSearch className="h-3.5 w-3.5" />
                  )}
                  {t.trigger_type === "schedule" ? "Schedule" : "File Trigger"}
                </span>
              </td>

              {/* Schedule / Source */}
              <td className="px-4 py-3 text-muted-foreground">
                {formatSchedule(t)}
              </td>

              {/* Env */}
              <td className="px-4 py-3">{envBadge(t.environment)}</td>

              {/* Runs */}
              <td className="px-4 py-3 text-right text-muted-foreground">
                {t.trigger_count}
              </td>

              {/* Last Run */}
              <td className="px-4 py-3 text-muted-foreground">
                {formatLastRun(t.last_triggered_at)}
              </td>

              {/* Actions */}
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  {/* Run Now */}
                  <button
                    onClick={() => onRunNow(t.id)}
                    disabled={runningId === t.id || deploymentStopped}
                    title={deploymentStopped ? "Deployment is stopped or disabled" : "Run Now"}
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                  >
                    {runningId === t.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                  </button>

                  {/* Edit */}
                  <button
                    onClick={() => onEdit(t)}
                    title="Edit"
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>

                  {/* Logs */}
                  <button
                    onClick={() => onLogs(t.id)}
                    title="View Logs"
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <List className="h-4 w-4" />
                  </button>

                  {/* Delete */}
                  <button
                    onClick={() => onDelete(t.id)}
                    title="Delete"
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </td>
            </tr>
          ); })}
        </tbody>
      </table>
    </div>
  );
}

// ── LogsSlideOver ─────────────────────────────────────────────────────────

// ── Log pairing helper ────────────────────────────────────────────────────
// Each run produces 2 DB records: "started" (fire time) + "success"/"error" (finish time).
// We pair them by matching the nearest "success"/"error" within 120 s of each "started".

interface PairedRun {
  key: string;
  startedAt: string;
  completedAt: string | null;
  status: "running" | "success" | "error";
  duration_ms: number | null;
  error_message: string | null;
  startPayload: Record<string, any> | null;       // from "started" entry: trigger_type, env, version, input
  completionPayload: Record<string, any> | null;  // from "success"/"error" entry: session_id, output
}

function pairLogs(logs: TriggerExecutionLog[]): PairedRun[] {
  const started = logs.filter((l) => l.status === "started");
  const completed = logs.filter((l) => l.status === "success" || l.status === "error");
  const usedIds = new Set<string>();
  const pairs: PairedRun[] = [];

  for (const s of started) {
    const startMs = new Date(s.triggered_at).getTime();
    let match: typeof completed[0] | null = null;
    let minDiff = Infinity;

    for (const c of completed) {
      if (usedIds.has(c.id)) continue;
      const diff = new Date(c.triggered_at).getTime() - startMs;
      if (diff >= 0 && diff < 120_000 && diff < minDiff) {
        minDiff = diff;
        match = c;
      }
    }

    if (match) {
      usedIds.add(match.id);
      pairs.push({
        key: s.id,
        startedAt: s.triggered_at,
        completedAt: match.triggered_at,
        status: match.status as "success" | "error",
        duration_ms: match.execution_duration_ms,
        error_message: match.error_message,
        startPayload: s.payload,
        completionPayload: match.payload,
      });
    } else {
      pairs.push({
        key: s.id,
        startedAt: s.triggered_at,
        completedAt: null,
        status: "running",
        duration_ms: null,
        error_message: null,
        startPayload: s.payload,
        completionPayload: null,
      });
    }
  }

  // Most recent first
  pairs.sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime());
  return pairs;
}

// ── LogsSlideOver ─────────────────────────────────────────────────────────

function LogsSlideOver({
  triggerId,
  triggerName,
  onClose,
}: {
  triggerId: string;
  triggerName: string;
  onClose: () => void;
}): JSX.Element {
  const { data: logs = [], isLoading, isFetching, refetch } = useGetTriggerLogs(triggerId);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  // Fetch immediately on open (refetchOnMount:"always" handles it, but this
  // ensures we get data even if the cache entry was recently populated)
  useEffect(() => { refetch(); }, [triggerId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Pair started + success/error entries into one row per run.
  // Running entries (started but no completion yet) sort to TOP since their
  // startedAt is the most recent timestamp.
  const runs = pairLogs(logs);
  const hasRunning = runs.some((r) => r.status === "running");

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative z-10 flex h-full w-[480px] flex-col bg-background shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="font-semibold text-foreground">Execution Logs</h2>
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              {triggerName}
              {hasRunning && (
                <span className="flex items-center gap-1 text-yellow-600">
                  <RefreshCw className="h-3 w-3 animate-spin" />
                  Running…
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              title="Refresh"
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
            >
              <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={onClose}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Sub-header */}
        <div className="border-b border-border bg-muted/30 px-5 py-1.5 text-[11px] text-muted-foreground">
          Auto-refreshes every 2 s &nbsp;·&nbsp; {runs.length} run(s)
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-5">
          {isLoading ? (
            <div className="flex h-32 items-center justify-center">
              <Loading />
            </div>
          ) : runs.length === 0 ? (
            <p className="text-center text-sm text-muted-foreground">No runs yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="pb-2 text-left">Run Time</th>
                  <th className="pb-2 text-left">Status</th>
                  <th className="pb-2 text-right">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {runs.map((run) => (
                  <React.Fragment key={run.key}>
                    <tr
                      onClick={() =>
                        run.status !== "running"
                          ? setExpandedKey(expandedKey === run.key ? null : run.key)
                          : undefined
                      }
                      className={`hover:bg-muted/30 ${run.status !== "running" ? "cursor-pointer" : ""}`}
                    >
                      <td className="py-2.5 text-muted-foreground">
                        {new Date(run.startedAt).toLocaleString()}
                      </td>
                      <td className="py-2.5">
                        {run.status === "running" ? (
                          <span className="flex items-center gap-1.5 text-yellow-600">
                            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                            Running…
                          </span>
                        ) : run.status === "success" ? (
                          <span className="flex items-center gap-1.5 text-green-600">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            Success
                          </span>
                        ) : (
                          <span className="flex items-center gap-1.5 text-red-600">
                            <XCircle className="h-3.5 w-3.5" />
                            Error
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 text-right text-muted-foreground">
                        {run.status === "running" ? (
                          <span className="text-yellow-500">—</span>
                        ) : run.duration_ms != null ? (
                          `${run.duration_ms}ms`
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                    {expandedKey === run.key && run.status !== "running" && (
                      <tr key={`${run.key}-detail`}>
                        <td colSpan={3} className="px-1 pb-3 pt-0">
                          <div className="rounded-md border border-border bg-muted/20 text-xs divide-y divide-border">

                            {/* ── Meta row ── */}
                            <div className="flex flex-wrap gap-x-4 gap-y-1 px-3 py-2 text-muted-foreground">
                              {run.startPayload?.environment && (
                                <span>Env: <strong>{run.startPayload.environment}</strong></span>
                              )}
                              {run.startPayload?.version && (
                                <span>Version: <strong>{run.startPayload.version}</strong></span>
                              )}
                              {run.startPayload?.trigger_type && (
                                <span>Type: <strong>{run.startPayload.trigger_type}</strong></span>
                              )}
                              {run.completionPayload?.session_id && (
                                <span className="font-mono">
                                  Session: {String(run.completionPayload.session_id).slice(0, 8)}…
                                </span>
                              )}
                              {run.duration_ms != null && (
                                <span>Duration: <strong>{run.duration_ms}ms</strong></span>
                              )}
                            </div>

                            {/* ── Output ── */}
                            {run.completionPayload?.output && (
                              <div className="px-3 py-2 space-y-0.5">
                                <p className="font-semibold text-muted-foreground uppercase tracking-wide text-[10px]">Output</p>
                                <pre className="whitespace-pre-wrap break-all text-foreground font-sans leading-relaxed">
                                  {run.completionPayload.output}
                                </pre>
                              </div>
                            )}

                            {/* ── Error ── */}
                            {run.error_message && (
                              <div className="px-3 py-2 space-y-0.5">
                                <p className="font-semibold text-red-600 uppercase tracking-wide text-[10px]">Error</p>
                                <pre className="whitespace-pre-wrap break-all text-red-700 dark:text-red-300 font-sans leading-relaxed">
                                  {run.error_message}
                                </pre>
                              </div>
                            )}

                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

// ── AddAutomationModal ────────────────────────────────────────────────────

type Step = 1 | 2;

const BLANK_SCHEDULE = {
  schedule_type: "interval" as "interval" | "cron",
  interval_minutes: 60,
  cron_expression: "0 9 * * 1-5",
};

const BLANK_FOLDER = {
  storage_type: "Azure Blob Storage",
  connector_id: "",
  poll_interval_seconds: 30,
  file_types: [] as string[],
  trigger_on: "New Files",
};

function AddSchedulerModal({
  editing,
  onClose,
}: {
  editing: TriggerInfo | null;
  onClose: () => void;
}): JSX.Element {
  // When editing, skip step 1 (agent selection) and go straight to config
  const [step, setStep] = useState<Step>(editing ? 2 : 1);
  const [selectedAgent, setSelectedAgent] = useState<AgentOption | null>(null);
  const [triggerType, setTriggerType] = useState<"schedule" | "folder_monitor">(
    editing?.trigger_type ?? "schedule",
  );
  const [scheduleForm, setScheduleForm] = useState(() => {
    if (editing?.trigger_type === "schedule" && editing.trigger_config) {
      const cfg = editing.trigger_config;
      return {
        schedule_type: (cfg.schedule_type ?? "interval") as "interval" | "cron",
        interval_minutes: cfg.interval_minutes ?? 60,
        cron_expression: cfg.cron_expression ?? "0 9 * * 1-5",
      };
    }
    return { ...BLANK_SCHEDULE };
  });
  const [folderForm, setFolderForm] = useState(() => {
    if (editing?.trigger_type === "folder_monitor" && editing.trigger_config) {
      const cfg = editing.trigger_config;
      return {
        storage_type: cfg.storage_type ?? "Azure Blob Storage",
        connector_id: cfg.connector_id ?? "",
        poll_interval_seconds: cfg.poll_interval_seconds ?? 30,
        file_types: cfg.file_types ?? [],
        trigger_on: cfg.trigger_on ?? "New Files",
      };
    }
    return { ...BLANK_FOLDER };
  });
  const [environment, setEnvironment] = useState<"uat" | "prod">(
    (editing?.environment as "uat" | "prod") ?? "prod",
  );

  // Use the same control panel hook as WorkflowsView — fetch both envs
  // NOTE: backend max size=100 (le=100 validation)
  const { data: uatData, isLoading: uatLoading } = useGetControlPanelAgents(
    { env: "uat", page: 1, size: 100 },
    { refetchOnWindowFocus: false },
  );
  const { data: prodData, isLoading: prodLoading } = useGetControlPanelAgents(
    { env: "prod", page: 1, size: 100 },
    { refetchOnWindowFocus: false },
  );

  const agentsLoading = uatLoading || prodLoading;

  // Build list keyed by deploy_id so each deployment version shows as a separate entry
  const agents = useMemo<AgentOption[]>(() => {
    const list: AgentOption[] = [];
    for (const item of uatData?.items ?? []) {
      list.push({
        deployId: item.deploy_id,
        agentId: item.agent_id,
        name: item.agent_name,
        environment: "uat",
        version: String(item.version_number).startsWith("v") ? String(item.version_number) : `v${item.version_number}`,
        isActive: item.is_active,
        isEnabled: item.is_enabled,
        inputType: item.input_type ?? "autonomous",
      });
    }
    for (const item of prodData?.items ?? []) {
      list.push({
        deployId: item.deploy_id,
        agentId: item.agent_id,
        name: item.agent_name,
        environment: "prod",
        version: String(item.version_number).startsWith("v") ? String(item.version_number) : `v${item.version_number}`,
        isActive: item.is_active,
        isEnabled: item.is_enabled,
        inputType: item.input_type ?? "autonomous",
      });
    }
    return list;
  }, [uatData, prodData]);

  const createMutation = useCreateTrigger();
  const updateMutation = useUpdateTrigger();
  const isSaving = createMutation.isPending || updateMutation.isPending;

  const handleSave = async () => {
    const config: Record<string, any> =
      triggerType === "schedule"
        ? scheduleForm.schedule_type === "cron"
          ? { schedule_type: "cron", cron_expression: scheduleForm.cron_expression }
          : { schedule_type: "interval", interval_minutes: scheduleForm.interval_minutes }
        : { ...folderForm };

    if (editing) {
      // Update existing trigger via PATCH
      await updateMutation.mutateAsync({
        triggerId: editing.id,
        payload: { trigger_config: config, environment },
      });
    } else {
      if (!selectedAgent) return;
      const payload: CreateTriggerPayload = {
        trigger_type: triggerType,
        trigger_config: config,
        environment,
        version: selectedAgent.version,
        deployment_id: selectedAgent.deployId,
      };
      await createMutation.mutateAsync({ agentId: selectedAgent.agentId, payload });
    }
    onClose();
  };

  const canProceed =
    step === 1
      ? selectedAgent !== null
      : triggerType === "schedule"
      ? true
      : editing ? true : Boolean(folderForm.connector_id);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[520px] rounded-xl bg-background shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="font-semibold text-foreground">
              {editing ? "Edit Automation" : "Add Automation"}
            </h2>
            <p className="text-xs text-muted-foreground">
              {editing
                ? "Update trigger configuration"
                : `Step ${step} of 2 — ${step === 1 ? "Select agent & type" : "Configure trigger"}`}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          {step === 1 ? (
            <Step1
              agents={agents}
              agentsLoading={agentsLoading}
              selectedAgent={selectedAgent}
              onSelectAgent={setSelectedAgent}
              triggerType={triggerType}
              onSelectType={setTriggerType}
            />
          ) : (
            <Step2
              triggerType={triggerType}
              scheduleForm={scheduleForm}
              folderForm={folderForm}
              environment={environment}
              onScheduleChange={(k, v) =>
                setScheduleForm((f) => ({ ...f, [k]: v }))
              }
              onFolderChange={(k, v) =>
                setFolderForm((f) => ({ ...f, [k]: v }))
              }
              onEnvChange={setEnvironment}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between border-t border-border px-6 py-4">
          {step === 2 && !editing ? (
            <button
              onClick={() => setStep(1)}
              className="rounded-md px-4 py-2 text-sm text-muted-foreground hover:bg-muted"
            >
              Back
            </button>
          ) : (
            <button
              onClick={onClose}
              className="rounded-md px-4 py-2 text-sm text-muted-foreground hover:bg-muted"
            >
              Cancel
            </button>
          )}

          {step === 1 ? (
            <button
              onClick={() => setStep(2)}
              disabled={!canProceed}
              className="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors bg-[var(--button-primary)] text-[var(--button-primary-foreground)] hover:bg-[var(--button-primary-hover)] disabled:opacity-50"
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              onClick={handleSave}
              disabled={!canProceed || isSaving}
              className="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors bg-[var(--button-primary)] text-[var(--button-primary-foreground)] hover:bg-[var(--button-primary-hover)] disabled:opacity-50"
            >
              {isSaving && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              {editing ? "Update Automation" : "Save Automation"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Step 1 ────────────────────────────────────────────────────────────────

function Step1({
  agents,
  agentsLoading,
  selectedAgent,
  onSelectAgent,
  triggerType,
  onSelectType,
}: {
  agents: AgentOption[];
  agentsLoading: boolean;
  selectedAgent: AgentOption | null;
  onSelectAgent: (a: AgentOption | null) => void;
  triggerType: "schedule" | "folder_monitor";
  onSelectType: (t: "schedule" | "folder_monitor") => void;
}): JSX.Element {
  return (
    <div className="space-y-5">
      {/* Agent selector */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">
          Agent
        </label>
        {agentsLoading ? (
          <div className="flex h-10 items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading published agents…
          </div>
        ) : agents.length === 0 ? (
          <div className="rounded-md border border-border bg-muted/30 px-3 py-3 text-sm text-muted-foreground">
            No published agents found. Publish an agent to UAT or PROD first to
            create an automation.
          </div>
        ) : (
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={selectedAgent?.deployId ?? ""}
            onChange={(e) => {
              const a = agents.find((ag) => ag.deployId === e.target.value);
              onSelectAgent(a ?? null);
            }}
          >
            <option value="" disabled>
              Select a published agent…
            </option>
            {agents.map((a) => {
              const stopped = !a.isActive || !a.isEnabled;
              const isChat = a.inputType === "chat";
              const disabled = stopped || isChat;
              return (
                <option key={a.deployId} value={a.deployId} disabled={disabled}>
                  {a.name} ({a.environment.toUpperCase()} {a.version})
                  {isChat
                    ? " — Chat agent (cannot schedule)"
                    : stopped
                      ? (a.isActive ? " — Disabled" : " — Stopped")
                      : ""}
                </option>
              );
            })}
          </select>
        )}
      </div>

      {/* Trigger type — Schedule only. File Trigger is auto-detected from
          FileTrigger nodes in the builder when an agent is published. */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">
          Trigger Type
        </label>
        <div className="flex items-center gap-3 rounded-lg border-2 border-primary bg-primary/5 px-4 py-3">
          <Clock className="h-5 w-5 text-primary" />
          <div>
            <p className="text-sm font-medium text-primary">Schedule</p>
            <p className="text-xs text-muted-foreground">Run on a cron or interval</p>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          File Trigger automations are created automatically when you publish an agent
          that contains a File Trigger node.
        </p>
      </div>
    </div>
  );
}

// ── Step 2 ────────────────────────────────────────────────────────────────

function Step2({
  triggerType,
  scheduleForm,
  folderForm,
  environment,
  onScheduleChange,
  onFolderChange,
  onEnvChange,
}: {
  triggerType: "schedule" | "folder_monitor";
  scheduleForm: typeof BLANK_SCHEDULE;
  folderForm: typeof BLANK_FOLDER;
  environment: "uat" | "prod";
  onScheduleChange: (k: keyof typeof BLANK_SCHEDULE, v: any) => void;
  onFolderChange: (k: keyof typeof BLANK_FOLDER, v: any) => void;
  onEnvChange: (e: "uat" | "prod") => void;
}): JSX.Element {
  return (
    <div className="space-y-5">
      {triggerType === "schedule" ? (
        <ScheduleConfig form={scheduleForm} onChange={onScheduleChange} />
      ) : (
        <FileTriggerConfig form={folderForm} onChange={onFolderChange} />
      )}

      {/* Environment */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">
          Environment
        </label>
        <div className="flex gap-3">
          {(["uat", "prod"] as const).map((e) => (
            <button
              key={e}
              onClick={() => onEnvChange(e)}
              className={`rounded-md border px-4 py-1.5 text-sm font-medium ${
                environment === e
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-muted-foreground"
              }`}
            >
              {e.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── ScheduleConfig ────────────────────────────────────────────────────────

function ScheduleConfig({
  form,
  onChange,
}: {
  form: typeof BLANK_SCHEDULE;
  onChange: (k: keyof typeof BLANK_SCHEDULE, v: any) => void;
}): JSX.Element {
  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">
          Schedule Type
        </label>
        <div className="flex gap-3">
          {(["interval", "cron"] as const).map((t) => (
            <button
              key={t}
              onClick={() => onChange("schedule_type", t)}
              className={`rounded-md border px-4 py-1.5 text-sm font-medium ${
                form.schedule_type === t
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-muted-foreground"
              }`}
            >
              {t === "interval" ? "Interval" : "Cron"}
            </button>
          ))}
        </div>
      </div>

      {form.schedule_type === "interval" ? (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-foreground">
            Run every (minutes)
          </label>
          <input
            type="number"
            min={1}
            value={form.interval_minutes}
            onChange={(e) => onChange("interval_minutes", parseInt(e.target.value) || 1)}
            className="w-32 rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            {form.interval_minutes < 60
              ? `Every ${form.interval_minutes} minutes`
              : form.interval_minutes % 60 === 0
              ? `Every ${form.interval_minutes / 60} hour(s)`
              : `Every ${form.interval_minutes} minutes`}
          </p>
        </div>
      ) : (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-foreground">
            Cron Expression
          </label>
          <input
            type="text"
            value={form.cron_expression}
            onChange={(e) => onChange("cron_expression", e.target.value)}
            placeholder="0 9 * * 1-5"
            className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            {parseCron(form.cron_expression)}
          </p>
        </div>
      )}
    </div>
  );
}

// ── FileTriggerConfig ───────────────────────────────────────────────────

function FileTriggerConfig({
  form,
  onChange,
}: {
  form: typeof BLANK_FOLDER;
  onChange: (k: keyof typeof BLANK_FOLDER, v: any) => void;
}): JSX.Element {
  const { data: connectors = [], isLoading } = useGetConnectorsByProvider(
    form.storage_type,
  );

  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">
          Storage Type
        </label>
        <div className="flex gap-3">
          {["Azure Blob Storage", "SharePoint"].map((st) => (
            <button
              key={st}
              onClick={() => onChange("storage_type", st)}
              className={`rounded-md border px-3 py-1.5 text-sm font-medium ${
                form.storage_type === st
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:border-muted-foreground"
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">
          Connector
        </label>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading connectors…
          </div>
        ) : connectors.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No {form.storage_type} connectors found. Add one on the Connectors page first.
          </p>
        ) : (
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={form.connector_id}
            onChange={(e) => onChange("connector_id", e.target.value)}
          >
            <option value="" disabled>
              Select a connector…
            </option>
            {connectors.map((c: any) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        )}
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">
          Poll Interval (seconds)
        </label>
        <input
          type="number"
          min={10}
          value={form.poll_interval_seconds}
          onChange={(e) =>
            onChange("poll_interval_seconds", parseInt(e.target.value) || 30)
          }
          className="w-32 rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">
          Trigger On
        </label>
        <select
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          value={form.trigger_on}
          onChange={(e) => onChange("trigger_on", e.target.value)}
        >
          <option>New Files</option>
          <option>Modified Files</option>
          <option>Both</option>
        </select>
      </div>
    </div>
  );
}

// ── Connector loader hook ─────────────────────────────────────────────────

function useGetConnectorsByProvider(storageType: string) {
  const providerMap: Record<string, string> = {
    "Azure Blob Storage": "azure_blob",
    SharePoint: "sharepoint",
  };
  const provider = providerMap[storageType];

  const { data: all = [], isLoading } = useGetConnectorCatalogue();

  const filtered = provider
    ? (all as any[]).filter((c: any) => c.provider === provider)
    : [];

  return { data: filtered, isLoading };
}
