import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { api } from "@/controllers/API/api";
import {
  AlertCircle,
  ChevronRight,
  Clock,
  DollarSign,
  Activity,
  Layers,
  Cpu,
  Calendar,
  Search,
  X,
  FolderOpen,
  Bot,
  TrendingUp,
  BarChart3,
  PieChart as PieChartIcon,
  ArrowUpRight,
  ArrowDownRight,
  XCircle,
  Timer,
} from "lucide-react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
  PieChart,
  Pie,
  Cell,
  Legend,
  ComposedChart,
} from "recharts";

// =============================================================================
// Theme Constants - Corporate Color Scheme
// =============================================================================

const THEME = {
  primary: "#da2128",        // Red for primary buttons and active states
  primaryHover: "#b81c22",   // Darker red for hover
  textMain: "#888888",       // Dark grey for main content
  textSecondary: "#555555",  // Light grey for secondary content
  success: "#10b981",        // Green for success states
  warning: "#f59e0b",        // Amber for warnings
  error: "#ef4444",          // Red for errors
  info: "#3b82f6",           // Blue for info
  chartColors: [
    "#da2128",  // Primary red
    "#3b82f6",  // Blue
    "#10b981",  // Green
    "#f59e0b",  // Amber
    "#8b5cf6",  // Purple
    "#ec4899",  // Pink
  ],
};

// =============================================================================
// Types
// =============================================================================

type DateRangePreset = "today" | "7d" | "30d" | "90d" | "all";

interface Filters {
  dateRange: DateRangePreset;
  search: string;
  models: string[];
}

interface LangfuseStatus {
  connected: boolean;
  host: string | null;
  message: string;
}

interface ModelUsageItem {
  model: string;
  call_count: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  avg_latency_ms: number | null;
}

interface DailyUsageItem {
  date: string;
  trace_count: number;
  observation_count: number;
  total_tokens: number;
  total_cost: number;
}

interface Metrics {
  total_traces: number;
  total_observations: number;
  total_sessions: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  by_model: ModelUsageItem[];
  by_date: DailyUsageItem[];
  top_agents: Array<{ name: string; count: number; tokens: number; cost: number }>;
  truncated?: boolean;
  fetched_trace_count?: number;
}

interface SessionListItem {
  session_id: string;
  trace_count: number;
  total_tokens: number;
  total_cost: number;
  first_trace_at: string | null;
  last_trace_at: string | null;
  models_used: string[];
  has_errors?: boolean;
  avg_latency_ms?: number | null;
}

interface TraceListItem {
  id: string;
  name: string | null;
  session_id: string | null;
  timestamp: string | null;
  total_tokens: number;
  total_cost: number;
  latency_ms: number | null;
  models_used: string[];
  observation_count: number;
  level?: string | null;
}

interface ObservationResponse {
  id: string;
  trace_id: string;
  name: string | null;
  type: string | null;
  model: string | null;
  start_time: string | null;
  end_time: string | null;
  latency_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost: number;
  input: unknown;
  output: unknown;
  level: string | null;
}

interface ScoreItem {
  id: string;
  name: string;
  value: number;
  source?: string | null;
  comment?: string | null;
  created_at?: string | null;
}

interface TraceDetailResponse {
  id: string;
  name: string | null;
  session_id: string | null;
  timestamp: string | null;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  latency_ms: number | null;
  observations: ObservationResponse[];
  scores?: ScoreItem[];
}

interface SessionDetailResponse {
  session_id: string;
  trace_count: number;
  total_tokens: number;
  total_cost: number;
  first_trace_at: string | null;
  last_trace_at: string | null;
  models_used: string[];
  traces: TraceListItem[];
}

interface AgentListItem {
  agent_id: string;
  agent_name: string | null;
  project_id: string | null;
  project_name: string | null;
  trace_count: number;
  session_count: number;
  total_tokens: number;
  total_cost: number;
  avg_latency_ms: number | null;
  models_used: string[];
  last_activity: string | null;
  error_count: number;
}

interface AgentDetailResponse {
  agent_id: string;
  agent_name: string | null;
  trace_count: number;
  session_count: number;
  observation_count: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  avg_latency_ms: number | null;
  first_activity: string | null;
  last_activity: string | null;
  models_used: Record<string, { tokens: number; cost: number; calls: number }>;
  sessions: SessionListItem[];
  by_date: DailyUsageItem[];
}

interface ProjectListItem {
  project_id: string;
  project_name: string;
  agent_count: number;
  trace_count: number;
  session_count: number;
  total_tokens: number;
  total_cost: number;
  last_activity: string | null;
}

interface ProjectDetailResponse {
  project_id: string;
  project_name: string | null;
  agent_count: number;
  trace_count: number;
  session_count: number;
  observation_count: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  avg_latency_ms: number | null;
  first_activity: string | null;
  last_activity: string | null;
  models_used: Record<string, { tokens: number; cost: number; calls: number }>;
  agents: AgentListItem[];
  by_date: DailyUsageItem[];
}

// =============================================================================
// Constants
// =============================================================================

const DATE_RANGE_LABELS: Record<DateRangePreset, string> = {
  today: "Today",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  all: "All time",
};

// =============================================================================
// Helper Functions
// =============================================================================

// Format date as YYYY-MM-DD in LOCAL timezone (not UTC)
function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getDateRangeParams(preset: DateRangePreset): { from_date?: string; to_date?: string } {
  if (preset === "all") return {};

  const now = new Date();
  // Use local date instead of UTC to match user's timezone
  const to_date = formatLocalDate(now);

  let from_date: string;
  switch (preset) {
    case "today":
      from_date = to_date;
      break;
    case "7d":
      from_date = formatLocalDate(new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000));
      break;
    case "30d":
      from_date = formatLocalDate(new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000));
      break;
    case "90d":
      from_date = formatLocalDate(new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000));
      break;
    default:
      return {};
  }

  return { from_date, to_date };
}

function formatCost(cost: number): string {
  if (cost === 0) return "$0.00";
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

function formatLatency(ms: number | null): string {
  if (ms === null) return "-";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  try {
    return new Date(dateStr).toLocaleString();
  } catch {
    return dateStr;
  }
}

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return tokens.toString();
}

function calculateTrend(data: DailyUsageItem[] | undefined, key: keyof DailyUsageItem): { value: number; direction: "up" | "down" | "neutral" } {
  if (!data || data.length < 2) return { value: 0, direction: "neutral" };

  const recent = data.slice(-7);
  const older = data.slice(-14, -7);

  if (recent.length === 0 || older.length === 0) return { value: 0, direction: "neutral" };

  const recentAvg = recent.reduce((sum, d) => sum + (Number(d[key]) || 0), 0) / recent.length;
  const olderAvg = older.reduce((sum, d) => sum + (Number(d[key]) || 0), 0) / older.length;

  if (olderAvg === 0) return { value: 0, direction: "neutral" };

  const change = ((recentAvg - olderAvg) / olderAvg) * 100;
  return {
    value: Math.abs(change),
    direction: change > 5 ? "up" : change < -5 ? "down" : "neutral",
  };
}

// =============================================================================
// API Functions
// =============================================================================

interface FetchMetricsParams {
  from_date?: string;
  to_date?: string;
  search?: string;
  models?: string;
  include_model_breakdown?: boolean;
  tz_offset?: number;
  fetch_all?: boolean;
}

// Get user's timezone offset in minutes (positive for east of UTC, e.g., IST = 330)
function getUserTimezoneOffset(): number {
  // getTimezoneOffset returns UTC - local, so we negate it
  // For IST (UTC+5:30), getTimezoneOffset() returns -330, so we negate to get +330
  return -new Date().getTimezoneOffset();
}

async function fetchStatus(): Promise<LangfuseStatus> {
  const response = await api.get<LangfuseStatus>("/api/observability/status");
  return response.data;
}

async function fetchMetrics(params: FetchMetricsParams = {}): Promise<Metrics> {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  if (params.search) searchParams.set("search", params.search);
  if (params.models) searchParams.set("models", params.models);
  if (params.include_model_breakdown) searchParams.set("include_model_breakdown", "true");
  // Always send timezone offset for correct date grouping
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.fetch_all) searchParams.set("fetch_all", "true");

  const queryString = searchParams.toString();
  const url = `/api/observability/metrics?${queryString}`;
  const response = await api.get<Metrics>(url);
  return response.data;
}

async function fetchSessions(params: FetchMetricsParams = {}): Promise<{ sessions: SessionListItem[]; total: number; truncated?: boolean; fetched_trace_count?: number }> {
  const searchParams = new URLSearchParams();
  searchParams.set("limit", "50");
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.fetch_all) searchParams.set("fetch_all", "true");

  const response = await api.get(`/api/observability/sessions?${searchParams.toString()}`);
  return response.data;
}

async function fetchSessionDetail(sessionId: string, params: FetchMetricsParams = {}): Promise<SessionDetailResponse> {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  const query = searchParams.toString();
  const response = await api.get<SessionDetailResponse>(`/api/observability/sessions/${encodeURIComponent(sessionId)}${query ? `?${query}` : ''}`);
  return response.data;
}

async function fetchTraceDetail(traceId: string): Promise<TraceDetailResponse> {
  const response = await api.get<TraceDetailResponse>(`/api/observability/traces/${traceId}`);
  return response.data;
}

async function fetchAgents(params: FetchMetricsParams = {}): Promise<{ agents: AgentListItem[]; total_count: number; truncated?: boolean; fetched_trace_count?: number }> {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  if (params.search) searchParams.set("search", params.search);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.fetch_all) searchParams.set("fetch_all", "true");

  const queryString = searchParams.toString();
  const url = queryString ? `/api/observability/agents?${queryString}` : "/api/observability/agents";
  const response = await api.get(url);
  return response.data;
}

async function fetchAgentDetail(agentId: string, params: FetchMetricsParams = {}): Promise<AgentDetailResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  if (params.fetch_all) searchParams.set("fetch_all", "true");
  const response = await api.get<AgentDetailResponse>(`/api/observability/agents/${agentId}?${searchParams.toString()}`);
  return response.data;
}

async function fetchProjects(params: FetchMetricsParams = {}): Promise<{ projects: ProjectListItem[]; total_count: number; truncated?: boolean; fetched_trace_count?: number }> {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.fetch_all) searchParams.set("fetch_all", "true");

  const queryString = searchParams.toString();
  const url = queryString ? `/api/observability/projects?${queryString}` : "/api/observability/projects";
  const response = await api.get(url);
  return response.data;
}

async function fetchProjectDetail(projectId: string, params: FetchMetricsParams = {}): Promise<ProjectDetailResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  if (params.fetch_all) searchParams.set("fetch_all", "true");
  const response = await api.get<ProjectDetailResponse>(`/api/observability/projects/${projectId}?${searchParams.toString()}`);
  return response.data;
}

// =============================================================================
// Enhanced Components
// =============================================================================

// Mini sparkline chart for KPI cards
function Sparkline({ data, dataKey, color = THEME.primary, height = 40 }: {
  data: any[];
  dataKey: string;
  color?: string;
  height?: number;
}) {
  if (!data || data.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`sparkGradient-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          strokeWidth={2}
          fill={`url(#sparkGradient-${dataKey})`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Trend indicator component
function TrendIndicator({ trend }: { trend: { value: number; direction: "up" | "down" | "neutral" } }) {
  // Don't show anything for neutral/no change
  if (trend.direction === "neutral") {
    return null;
  }

  const isUp = trend.direction === "up";
  const color = isUp ? THEME.success : THEME.error;
  const Icon = isUp ? ArrowUpRight : ArrowDownRight;

  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium" style={{ color }}>
      <Icon className="h-3 w-3" />
      <span>{trend.value.toFixed(1)}%</span>
    </span>
  );
}

// Enhanced KPI Card with sparkline and trend
function EnhancedStatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  sparklineData,
  sparklineKey,
  accentColor = THEME.primary,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ElementType;
  trend?: { value: number; direction: "up" | "down" | "neutral" };
  sparklineData?: any[];
  sparklineKey?: string;
  accentColor?: string;
}) {
  return (
    <Card className="relative overflow-hidden border-0 shadow-sm hover:shadow-md transition-shadow">
      <div
        className="absolute top-0 left-0 w-1 h-full"
        style={{ backgroundColor: accentColor }}
      />
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2 pl-5">
        <CardTitle className="text-sm font-medium" style={{ color: THEME.textSecondary }}>
          {title}
        </CardTitle>
        {Icon && (
          <div
            className="p-2 rounded-lg"
            style={{ backgroundColor: `${accentColor}10` }}
          >
            <Icon className="h-4 w-4" style={{ color: accentColor }} />
          </div>
        )}
      </CardHeader>
      <CardContent className="pl-5">
        <div className="flex items-end justify-between">
          <div>
            <div className="text-2xl font-bold" style={{ color: THEME.textMain }}>
              {value}
            </div>
            {subtitle && (
              <p className="text-xs mt-1" style={{ color: THEME.textSecondary }}>
                {subtitle}
              </p>
            )}
            {trend && (
              <div className="mt-2">
                <TrendIndicator trend={trend} />
              </div>
            )}
          </div>
          {sparklineData && sparklineKey && (
            <div className="w-24 h-10">
              <Sparkline
                data={sparklineData}
                dataKey={sparklineKey}
                color={accentColor}
              />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// Progress bar component
function ProgressBar({ value, max, color = THEME.primary, showLabel = true }: {
  value: number;
  max: number;
  color?: string;
  showLabel?: boolean;
}) {
  const percentage = max > 0 ? (value / max) * 100 : 0;

  return (
    <div className="w-full">
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(100, percentage)}%`, backgroundColor: color }}
          />
        </div>
        {showLabel && (
          <span className="text-xs font-medium min-w-[40px] text-right" style={{ color: THEME.textSecondary }}>
            {percentage.toFixed(0)}%
          </span>
        )}
      </div>
    </div>
  );
}

// Recent Agent Activity Panel
function RecentAgentActivityPanel({ agentsData }: {
  agentsData: { agents: AgentListItem[]; total_count: number; truncated?: boolean; fetched_trace_count?: number } | undefined;
}) {
  const recentAgents = useMemo(() => {
    if (!agentsData?.agents) return [];
    // Sort by last_activity (most recent first) and take top 4
    return [...agentsData.agents]
      .filter(a => a.last_activity)
      .sort((a, b) => {
        const dateA = new Date(a.last_activity || 0).getTime();
        const dateB = new Date(b.last_activity || 0).getTime();
        return dateB - dateA;
      })
      .slice(0, 4);
  }, [agentsData]);

  const formatRelativeTime = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  return (
    <Card className="border-0 shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2" style={{ color: THEME.textSecondary }}>
          <Activity className="h-4 w-4" />
          Recent Agent Activity
        </CardTitle>
      </CardHeader>
      <CardContent>
        {recentAgents.length === 0 ? (
          <div className="text-center py-4">
            <Activity className="h-8 w-8 mx-auto mb-2 text-gray-300" />
            <p className="text-sm" style={{ color: THEME.textSecondary }}>No recent activity</p>
          </div>
        ) : (
          <div className="space-y-3">
            {recentAgents.map((agent) => (
              <div
                key={agent.agent_id}
                className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <div
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{
                    backgroundColor: agent.error_count > 0 ? THEME.error : THEME.success,
                  }}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate" style={{ color: THEME.textMain }}>
                    {agent.agent_name || 'Unnamed Agent'}
                  </p>
                  <p className="text-xs" style={{ color: THEME.textSecondary }}>
                    {agent.session_count} sessions • {agent.error_count > 0 ? `${agent.error_count} errors` : 'No errors'}
                  </p>
                </div>
                <div className="text-right flex-shrink-0">
                  <p className="text-xs font-medium" style={{ color: THEME.textSecondary }}>
                    {formatRelativeTime(agent.last_activity)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Custom tooltip for charts
function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload || !payload.length) return null;

  return (
    <div className="bg-white border shadow-lg rounded-lg p-3">
      <p className="text-sm font-medium mb-2" style={{ color: THEME.textMain }}>{label}</p>
      {payload.map((entry: any, idx: number) => (
        <div key={idx} className="flex items-center gap-2 text-sm">
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span style={{ color: THEME.textSecondary }}>{entry.name}:</span>
          <span className="font-medium" style={{ color: THEME.textMain }}>
            {typeof entry.value === 'number' && entry.name?.toLowerCase().includes('cost')
              ? formatCost(entry.value)
              : typeof entry.value === 'number' && entry.name?.toLowerCase().includes('token')
              ? formatTokens(entry.value)
              : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// =============================================================================
// Truncation Banner Component
// =============================================================================

function TruncationBanner({ fetchedCount, onLoadAll, isLoading }: {
  fetchedCount: number;
  onLoadAll: () => void;
  isLoading: boolean;
}) {
  return (
    <Alert className="border-amber-200 bg-amber-50">
      <AlertCircle className="h-4 w-4" style={{ color: THEME.warning }} />
      <AlertTitle className="text-sm font-medium" style={{ color: THEME.textMain }}>
        Showing data from {fetchedCount.toLocaleString()} traces (limit reached)
      </AlertTitle>
      <AlertDescription className="flex items-center justify-between">
        <span className="text-sm" style={{ color: THEME.textSecondary }}>
          There may be more traces. Narrow your date range for faster results, or load all data.
        </span>
        <Button
          size="sm"
          variant="outline"
          onClick={onLoadAll}
          disabled={isLoading}
          className="ml-4 shrink-0 border-amber-300 hover:bg-amber-100"
        >
          {isLoading ? "Loading..." : "Load All Data"}
        </Button>
      </AlertDescription>
    </Alert>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export default function ObservabilityPage(): JSX.Element {
  const queryClient = useQueryClient();
  // State
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [expandedObservation, setExpandedObservation] = useState<string | null>(null);
  const [fetchAllMode, setFetchAllMode] = useState(false);

  // Filter state — default to 7d so data is visible on first load
  const [filters, setFilters] = useState<Filters>({
    dateRange: "7d",
    search: "",
    models: [],
  });
  const [searchInput, setSearchInput] = useState("");

  // Tab-specific search states for client-side filtering
  const [agentSearch, setAgentSearch] = useState("");
  const [projectSearch, setProjectSearch] = useState("");
  const [sessionSearch, setSessionSearch] = useState("");
  const [modelSearch, setModelSearch] = useState("");
  const [usageSearch, setUsageSearch] = useState("");
  const [isFilterApplying, setIsFilterApplying] = useState(false);
  const filterApplyStartedAtRef = useRef<number | null>(null);
  const filterApplyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const filterFollowupRefetchTimeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const emptyListsRecoveryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const filterApplyBaselineUpdatedAtRef = useRef<{ metrics: number; sessions: number; agents: number; projects: number } | null>(null);

  const markFiltersApplying = useCallback(() => {
    filterApplyStartedAtRef.current = Date.now();
    filterApplyBaselineUpdatedAtRef.current = null;
    setIsFilterApplying(true);
    if (filterApplyTimeoutRef.current) {
      clearTimeout(filterApplyTimeoutRef.current);
    }
    // Safety timeout so indicator does not get stuck if network state is ambiguous
    filterApplyTimeoutRef.current = setTimeout(() => {
      setIsFilterApplying(false);
      filterApplyStartedAtRef.current = null;
      filterApplyTimeoutRef.current = null;
    }, 30000);

    if (filterFollowupRefetchTimeoutsRef.current.length > 0) {
      filterFollowupRefetchTimeoutsRef.current.forEach(clearTimeout);
      filterFollowupRefetchTimeoutsRef.current = [];
    }

    // Trigger follow-up refetches so backend SWR-updated aggregates are picked up quickly.
    [1200, 3200].forEach((delay) => {
      const timeoutId = setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["observability-metrics"] });
        queryClient.invalidateQueries({ queryKey: ["observability-sessions"] });
        queryClient.invalidateQueries({ queryKey: ["observability-agents"] });
        queryClient.invalidateQueries({ queryKey: ["observability-projects"] });
      }, delay);
      filterFollowupRefetchTimeoutsRef.current.push(timeoutId);
    });
  }, [queryClient]);

  // Compute date params from filter
  const dateParams = useMemo(() => ({
    ...getDateRangeParams(filters.dateRange),
    tz_offset: getUserTimezoneOffset(),
    ...(fetchAllMode ? { fetch_all: true } : {}),
  }), [filters.dateRange, fetchAllMode]);

  const handleDateRangeChange = useCallback((value: DateRangePreset) => {
    markFiltersApplying();
    setFetchAllMode(false);
    setFilters(prev => ({ ...prev, dateRange: value }));
  }, [markFiltersApplying]);

  // Queries
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["langfuse-status"],
    queryFn: fetchStatus,
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
  });

  const includeModelBreakdown = activeTab === "models";

  const { data: metrics, isLoading: metricsLoading, isFetching: metricsFetching, dataUpdatedAt: metricsUpdatedAt } = useQuery({
    queryKey: ["observability-metrics", filters.dateRange, filters.search, filters.models.join(","), fetchAllMode, includeModelBreakdown],
    queryFn: () => fetchMetrics({
      ...dateParams,
      search: filters.search || undefined,
      models: filters.models.length > 0 ? filters.models.join(",") : undefined,
      include_model_breakdown: includeModelBreakdown,
    }),
    enabled: !!status?.connected,
    refetchInterval: activeTab === "overview" ? 60000 : false,
    staleTime: 30000,
    placeholderData: (previousData: any) => previousData,
    refetchOnWindowFocus: false,
  });

  const { data: sessionsData, isLoading: sessionsLoading, isFetching: sessionsFetching, refetch: refetchSessions, dataUpdatedAt: sessionsUpdatedAt } = useQuery({
    queryKey: ["observability-sessions", filters.dateRange, fetchAllMode],
    queryFn: () => fetchSessions(dateParams),
    enabled: !!status?.connected,
    refetchInterval: activeTab === "sessions" ? 60000 : false,
    staleTime: 30000,
    placeholderData: (previousData: any) => previousData,
    refetchOnWindowFocus: false,
  });

  const { data: agentsData, isLoading: agentsLoading, isFetching: agentsFetching, refetch: refetchAgents, dataUpdatedAt: agentsUpdatedAt } = useQuery({
    queryKey: ["observability-agents", filters.dateRange, fetchAllMode],
    queryFn: () => fetchAgents({
      ...dateParams,
    }),
    enabled: !!status?.connected,
    refetchInterval: activeTab === "agents" ? 60000 : false,
    staleTime: 30000,
    placeholderData: (previousData: any) => previousData,
    refetchOnWindowFocus: false,
  });

  const { data: projectsData, isLoading: projectsLoading, isFetching: projectsFetching, refetch: refetchProjects, dataUpdatedAt: projectsUpdatedAt } = useQuery({
    queryKey: ["observability-projects", filters.dateRange, fetchAllMode],
    queryFn: () => fetchProjects(dateParams),
    enabled: !!status?.connected,
    refetchInterval: activeTab === "projects" ? 60000 : false,
    staleTime: 30000,
    placeholderData: (previousData: any) => previousData,
    refetchOnWindowFocus: false,
  });

  const { data: sessionDetail, isLoading: sessionDetailLoading, isFetching: sessionDetailFetching } = useQuery({
    queryKey: ["session-detail", selectedSession, filters.dateRange],
    queryFn: () => fetchSessionDetail(selectedSession!, dateParams),
    enabled: !!selectedSession,
    staleTime: 30000,
    placeholderData: (previousData: any) => previousData,
    refetchOnWindowFocus: false,
  });

  const { data: traceDetail, isLoading: traceDetailLoading, isFetching: traceDetailFetching, isError: traceDetailError } = useQuery({
    queryKey: ["trace-detail", selectedTrace],
    queryFn: () => fetchTraceDetail(selectedTrace!),
    enabled: !!selectedTrace,
    staleTime: 5000,
    retry: false,
    placeholderData: (previousData: any) => previousData,
    refetchOnWindowFocus: false,
  });

  const { data: agentDetail, isLoading: agentDetailLoading, isFetching: agentDetailFetching } = useQuery({
    queryKey: ["agent-detail", selectedAgent, filters.dateRange],
    queryFn: () => fetchAgentDetail(selectedAgent!, dateParams),
    enabled: !!selectedAgent,
    staleTime: 30000,
    placeholderData: (previousData: any) => previousData,
    refetchOnWindowFocus: false,
  });

  const { data: projectDetail, isLoading: projectDetailLoading, isFetching: projectDetailFetching } = useQuery({
    queryKey: ["project-detail", selectedProject, filters.dateRange, fetchAllMode],
    queryFn: () => fetchProjectDetail(selectedProject!, dateParams),
    enabled: !!selectedProject,
    staleTime: 30000,
    placeholderData: (previousData: any) => previousData,
    refetchOnWindowFocus: false,
  });

  const isAnyPrimaryQueryLoading =
    metricsLoading ||
    metricsFetching ||
    agentsLoading ||
    agentsFetching ||
    sessionsLoading ||
    sessionsFetching ||
    projectsLoading ||
    projectsFetching ||
    sessionDetailLoading ||
    sessionDetailFetching ||
    agentDetailLoading ||
    agentDetailFetching ||
    projectDetailLoading ||
    projectDetailFetching;

  useEffect(() => {
    if (!isFilterApplying) return;
    if (!filterApplyBaselineUpdatedAtRef.current) {
      filterApplyBaselineUpdatedAtRef.current = {
        metrics: metricsUpdatedAt,
        sessions: sessionsUpdatedAt,
        agents: agentsUpdatedAt,
        projects: projectsUpdatedAt,
      };
    }
  }, [
    isFilterApplying,
    metricsUpdatedAt,
    sessionsUpdatedAt,
    agentsUpdatedAt,
    projectsUpdatedAt,
  ]);

  useEffect(() => {
    if (!isFilterApplying) return;

    const baseline = filterApplyBaselineUpdatedAtRef.current;
    if (!baseline) return;
    const allCoreQueriesUpdated =
      metricsUpdatedAt > baseline.metrics &&
      sessionsUpdatedAt > baseline.sessions &&
      agentsUpdatedAt > baseline.agents &&
      projectsUpdatedAt > baseline.projects;

    if (!allCoreQueriesUpdated) return;
    if (isAnyPrimaryQueryLoading) return;

    const startedAt = filterApplyStartedAtRef.current ?? Date.now();
    const elapsed = Date.now() - startedAt;
    const minVisibleMs = 1200;
    const remaining = Math.max(0, minVisibleMs - elapsed);

    const timer = setTimeout(() => {
      setIsFilterApplying(false);
      filterApplyStartedAtRef.current = null;
      filterApplyBaselineUpdatedAtRef.current = null;
      if (filterApplyTimeoutRef.current) {
        clearTimeout(filterApplyTimeoutRef.current);
        filterApplyTimeoutRef.current = null;
      }
    }, remaining);

    return () => clearTimeout(timer);
  }, [
    isFilterApplying,
    isAnyPrimaryQueryLoading,
    metricsUpdatedAt,
    sessionsUpdatedAt,
    agentsUpdatedAt,
    projectsUpdatedAt,
  ]);

  useEffect(() => {
    const hasOverviewTraces = (metrics?.total_traces ?? 0) > 0;
    if (!hasOverviewTraces) return;

    const agentsEmpty = (agentsData?.agents?.length ?? 0) === 0;
    const projectsEmpty = (projectsData?.projects?.length ?? 0) === 0;
    const sessionsEmpty = (sessionsData?.sessions?.length ?? 0) === 0;
    const shouldRecover = agentsEmpty || projectsEmpty || sessionsEmpty;

    if (!shouldRecover) return;
    if (agentsFetching || projectsFetching || sessionsFetching) return;

    if (emptyListsRecoveryTimeoutRef.current) {
      clearTimeout(emptyListsRecoveryTimeoutRef.current);
    }

    emptyListsRecoveryTimeoutRef.current = setTimeout(() => {
      if (agentsEmpty) void refetchAgents();
      if (projectsEmpty) void refetchProjects();
      if (sessionsEmpty) void refetchSessions();
      emptyListsRecoveryTimeoutRef.current = null;
    }, 900);

    return () => {
      if (emptyListsRecoveryTimeoutRef.current) {
        clearTimeout(emptyListsRecoveryTimeoutRef.current);
        emptyListsRecoveryTimeoutRef.current = null;
      }
    };
  }, [
    metrics?.total_traces,
    agentsData?.agents?.length,
    projectsData?.projects?.length,
    sessionsData?.sessions?.length,
    agentsFetching,
    projectsFetching,
    sessionsFetching,
    refetchAgents,
    refetchProjects,
    refetchSessions,
  ]);

  useEffect(() => {
    return () => {
      if (filterApplyTimeoutRef.current) {
        clearTimeout(filterApplyTimeoutRef.current);
      }
      if (filterFollowupRefetchTimeoutsRef.current.length > 0) {
        filterFollowupRefetchTimeoutsRef.current.forEach(clearTimeout);
      }
      if (emptyListsRecoveryTimeoutRef.current) {
        clearTimeout(emptyListsRecoveryTimeoutRef.current);
      }
    };
  }, []);

  // Get available models from metrics for filter dropdown
  const availableModels = useMemo(() => {
    return metrics?.by_model?.map(m => m.model) || [];
  }, [metrics?.by_model]);

  // Calculate trends
  const tokensTrend = useMemo(() => calculateTrend(metrics?.by_date, "total_tokens"), [metrics?.by_date]);
  const costTrend = useMemo(() => calculateTrend(metrics?.by_date, "total_cost"), [metrics?.by_date]);
  const tracesTrend = useMemo(() => calculateTrend(metrics?.by_date, "trace_count"), [metrics?.by_date]);

  // Filtered data for each tab (client-side filtering)
  const filteredAgents = useMemo(() => {
    if (!agentsData?.agents) return [];
    if (!agentSearch.trim()) return agentsData.agents;
    const search = agentSearch.toLowerCase();
    return agentsData.agents.filter(agent =>
      agent.agent_name?.toLowerCase().includes(search)
    );
  }, [agentsData?.agents, agentSearch]);

  const filteredProjects = useMemo(() => {
    if (!projectsData?.projects) return [];
    if (!projectSearch.trim()) return projectsData.projects;
    const search = projectSearch.toLowerCase();
    return projectsData.projects.filter(project =>
      project.project_name?.toLowerCase().includes(search)
    );
  }, [projectsData?.projects, projectSearch]);

  const filteredSessions = useMemo(() => {
    if (!sessionsData?.sessions) return [];
    if (!sessionSearch.trim()) return sessionsData.sessions;
    const search = sessionSearch.toLowerCase();
    return sessionsData.sessions.filter(session =>
      session.session_id?.toLowerCase().includes(search) ||
      session.models_used?.some(model => model.toLowerCase().includes(search))
    );
  }, [sessionsData?.sessions, sessionSearch]);

  const filteredModels = useMemo(() => {
    if (!metrics?.by_model) return [];
    if (!modelSearch.trim()) return metrics.by_model;
    const search = modelSearch.toLowerCase();
    return metrics.by_model.filter(model =>
      model.model?.toLowerCase().includes(search)
    );
  }, [metrics?.by_model, modelSearch]);

  const filteredUsageData = useMemo(() => {
    if (!metrics?.by_date) return [];
    if (!usageSearch.trim()) return metrics.by_date;
    const search = usageSearch.toLowerCase();
    return metrics.by_date.filter(day =>
      day.date?.toLowerCase().includes(search)
    );
  }, [metrics?.by_date, usageSearch]);

  const hasAnyAgentRows = (agentsData?.agents?.length ?? 0) > 0;
  const hasAnyProjectRows = (projectsData?.projects?.length ?? 0) > 0;
  const hasAnySessionRows = (sessionsData?.sessions?.length ?? 0) > 0;

  const agentsTabLoading =
    agentsLoading && !agentsData;
  const projectsTabLoading =
    projectsLoading && !projectsData;
  const sessionsTabLoading =
    sessionsLoading && !sessionsData;

  // Handle search submit
  const handleSearch = useCallback(() => {
    markFiltersApplying();
    setFilters(prev => ({ ...prev, search: searchInput }));
  }, [searchInput, markFiltersApplying]);

  // Loading state
  if (statusLoading) {
    return (
      <div className="flex h-full w-full flex-col overflow-auto bg-gray-50 p-6">
        <Skeleton className="h-8 w-48 mb-6" />
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      </div>
    );
  }

  // Not connected state
  if (!status?.connected) {
    return (
      <div className="flex h-full w-full flex-col overflow-auto bg-gray-50 p-6">
        <h1 className="text-2xl font-bold mb-6" style={{ color: THEME.textMain }}>Observability</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Langfuse Not Connected</AlertTitle>
          <AlertDescription>
            {status?.message || "Unable to connect to Langfuse. Please configure LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST environment variables."}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const hasData = (metrics?.total_traces ?? 0) > 0;

  return (
    <div className="flex h-full w-full flex-col overflow-auto bg-gray-50">
      {/* Header */}
      <div className="border-b bg-white px-8 py-6 shadow-sm">
        <div className="flex items-center gap-3">
          <BarChart3 className="h-7 w-7" style={{ color: THEME.primary }} />
          <div>
            <h1 className="text-2xl font-semibold" style={{ color: THEME.textMain }}>
              Observability
            </h1>
            <p className="text-sm" style={{ color: THEME.textSecondary }}>
              Monitor your AI usage, costs, and performance metrics
            </p>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-auto p-6 space-y-6">
        {/* Filter Bar */}
        <div className="flex flex-wrap items-center gap-3 p-4 bg-white rounded-xl border shadow-sm">
          {/* Date Range Filter */}
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4" style={{ color: THEME.textSecondary }} />
            <Select
              value={filters.dateRange}
              onValueChange={(value: DateRangePreset) => handleDateRangeChange(value)}
            >
              <SelectTrigger className="w-[140px] h-9 bg-gray-50 border-gray-200">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(DATE_RANGE_LABELS) as DateRangePreset[]).map(key => (
                  <SelectItem key={key} value={key}>{DATE_RANGE_LABELS[key]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Search Input */}
          <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-[400px]">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
              <Input
                placeholder="Search by trace name..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                className="pl-9 h-9 bg-gray-50 border-gray-200"
              />
            </div>
            <Button
              size="sm"
              onClick={handleSearch}
              className="h-9"
              style={{ backgroundColor: THEME.primary }}
            >
              Search
            </Button>
          </div>

          {/* Model Filter */}
          {availableModels.length > 0 && (
            <div className="flex items-center gap-2">
              <Cpu className="h-4 w-4" style={{ color: THEME.textSecondary }} />
              <Select
                value={filters.models.length === 1 ? filters.models[0] : filters.models.length > 1 ? "multiple" : "all"}
                onValueChange={(value) => {
                  markFiltersApplying();
                  if (value === "all") {
                    setFilters(prev => ({ ...prev, models: [] }));
                  } else if (value !== "multiple") {
                    setFilters(prev => ({ ...prev, models: [value] }));
                  }
                }}
              >
                <SelectTrigger className="w-[180px] h-9 bg-gray-50 border-gray-200">
                  <SelectValue placeholder="All models" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All models</SelectItem>
                  {availableModels.map(model => (
                    <SelectItem key={model} value={model}>
                      {model.split("/").pop() || model}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Clear Filters */}
          {(filters.search || filters.models.length > 0 || filters.dateRange !== "7d") && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                markFiltersApplying();
                setFilters({ dateRange: "7d", search: "", models: [] });
                setSearchInput("");
                setFetchAllMode(false);
              }}
              className="h-9"
              style={{ color: THEME.textSecondary }}
            >
              <X className="h-4 w-4 mr-1" />
              Clear
            </Button>
          )}

          {/* Global refreshing indicator — shows a subtle spinner whenever any query is background-fetching */}
          {(isAnyPrimaryQueryLoading || isFilterApplying) && (
            <div className="flex items-center gap-1.5 ml-auto">
              <div className="h-3.5 w-3.5 rounded-full border-2 border-t-transparent animate-spin" style={{ borderColor: THEME.primary, borderTopColor: 'transparent' }} />
              <span className="text-xs" style={{ color: THEME.textSecondary }}>Updating…</span>
            </div>
          )}

          {/* Active Filters Display */}
          {filters.search && (
            <Badge variant="secondary" className="gap-1 bg-gray-100">
              Search: {filters.search}
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, search: "" }));
                  setSearchInput("");
                }}
                className="ml-1 hover:opacity-70"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          )}
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="bg-white border shadow-sm p-1 rounded-lg">
            {[
              { value: "overview", label: "Overview", icon: BarChart3 },
              { value: "agents", label: "Agents", icon: Bot },
              { value: "projects", label: "Projects", icon: FolderOpen },
              { value: "sessions", label: "Sessions", icon: Clock },
              { value: "models", label: "Models", icon: Cpu },
              { value: "usage", label: "Usage", icon: Activity },
            ].map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                className="flex items-center gap-2 data-[state=active]:shadow-sm px-4"
                style={{
                  color: activeTab === tab.value ? THEME.primary : THEME.textSecondary,
                }}
              >
                <tab.icon className="h-4 w-4" />
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* Overview Tab */}
          <TabsContent value="overview" className="space-y-6">
            {metrics?.truncated && !fetchAllMode && (
              <TruncationBanner
                fetchedCount={metrics.fetched_trace_count ?? 0}
                onLoadAll={() => setFetchAllMode(true)}
                isLoading={metricsLoading}
              />
            )}
            {metricsLoading ? (
              <div className="grid gap-4 md:grid-cols-4">
                {[1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-32" />
                ))}
              </div>
            ) : (
              <>
                {/* KPI Cards Row */}
                <div className="grid gap-4 md:grid-cols-4">
                  <EnhancedStatCard
                    title="Total Traces"
                    value={metrics?.total_traces ?? 0}
                    icon={Activity}
                    trend={tracesTrend}
                    sparklineData={metrics?.by_date}
                    sparklineKey="trace_count"
                    accentColor={THEME.primary}
                  />
                  <EnhancedStatCard
                    title="Total Tokens"
                    value={formatTokens(metrics?.total_tokens ?? 0)}
                    subtitle={`${formatTokens(metrics?.input_tokens ?? 0)} in / ${formatTokens(metrics?.output_tokens ?? 0)} out`}
                    icon={Layers}
                    trend={tokensTrend}
                    sparklineData={metrics?.by_date}
                    sparklineKey="total_tokens"
                    accentColor={THEME.chartColors[1]}
                  />
                  <EnhancedStatCard
                    title="Total Cost"
                    value={formatCost(metrics?.total_cost_usd ?? 0)}
                    icon={DollarSign}
                    trend={costTrend}
                    sparklineData={metrics?.by_date}
                    sparklineKey="total_cost"
                    accentColor={THEME.chartColors[2]}
                  />
                  <EnhancedStatCard
                    title="Sessions"
                    value={metrics?.total_sessions ?? 0}
                    icon={Clock}
                    accentColor={THEME.chartColors[3]}
                  />
                </div>

                {/* Cost Analysis Chart - Primary visual */}
                {metrics?.by_date && metrics.by_date.length > 0 && (
                  <Card className="border-0 shadow-sm">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <DollarSign className="h-5 w-5" style={{ color: THEME.chartColors[2] }} />
                        Cost Analysis
                      </CardTitle>
                      <CardDescription style={{ color: THEME.textSecondary }}>
                        Daily cost trend with activity correlation
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <ResponsiveContainer width="100%" height={220}>
                        <ComposedChart data={metrics.by_date}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                          <XAxis
                            dataKey="date"
                            tick={{ fontSize: 12, fill: THEME.textSecondary }}
                            tickFormatter={(value) => value.slice(5)}
                            axisLine={{ stroke: '#e5e7eb' }}
                          />
                          <YAxis
                            yAxisId="left"
                            tick={{ fontSize: 12, fill: THEME.textSecondary }}
                            tickFormatter={(value) => formatCost(value)}
                            axisLine={{ stroke: '#e5e7eb' }}
                          />
                          <YAxis
                            yAxisId="right"
                            orientation="right"
                            tick={{ fontSize: 12, fill: THEME.textSecondary }}
                            axisLine={{ stroke: '#e5e7eb' }}
                          />
                          <Tooltip content={<CustomTooltip />} />
                          <Legend />
                          <Bar
                            yAxisId="right"
                            dataKey="trace_count"
                            fill={THEME.chartColors[1]}
                            opacity={0.3}
                            radius={[4, 4, 0, 0]}
                            name="Traces"
                          />
                          <Line
                            yAxisId="left"
                            type="monotone"
                            dataKey="total_cost"
                            stroke={THEME.chartColors[2]}
                            strokeWidth={2}
                            dot={{ r: 4, fill: THEME.chartColors[2] }}
                            activeDot={{ r: 6 }}
                            name="Cost"
                          />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </CardContent>
                  </Card>
                )}

                {/* Agent Activity & Performance Row */}
                <div className="grid gap-4 md:grid-cols-2">
                  <RecentAgentActivityPanel agentsData={agentsData} />

                  {/* Performance Metrics Card */}
                  <Card className="border-0 shadow-sm">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm font-medium flex items-center gap-2" style={{ color: THEME.textSecondary }}>
                        <Timer className="h-4 w-4" />
                        Performance
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div>
                        <div className="flex justify-between text-sm mb-2">
                          <span style={{ color: THEME.textSecondary }}>Avg Latency</span>
                          <span className="font-medium" style={{ color: THEME.textMain }}>
                            {formatLatency(metrics?.avg_latency_ms ?? null)}
                          </span>
                        </div>
                        <ProgressBar
                          value={metrics?.avg_latency_ms ?? 0}
                          max={10000}
                          color={THEME.chartColors[1]}
                        />
                      </div>
                      <div>
                        <div className="flex justify-between text-sm mb-2">
                          <span style={{ color: THEME.textSecondary }}>P95 Latency</span>
                          <span className="font-medium" style={{ color: THEME.textMain }}>
                            {formatLatency(metrics?.p95_latency_ms ?? null)}
                          </span>
                        </div>
                        <ProgressBar
                          value={metrics?.p95_latency_ms ?? 0}
                          max={15000}
                          color={THEME.chartColors[3]}
                        />
                      </div>
                      <div>
                        <div className="flex justify-between text-sm mb-2">
                          <span style={{ color: THEME.textSecondary }}>Observations</span>
                          <span className="font-medium" style={{ color: THEME.textMain }}>
                            {metrics?.total_observations ?? 0}
                          </span>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Charts Row */}
                <div className="grid gap-4 md:grid-cols-2">
                  {/* Tokens Over Time Chart */}
                  {metrics?.by_date && metrics.by_date.length > 0 && (
                    <Card className="border-0 shadow-sm">
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                          <TrendingUp className="h-5 w-5" style={{ color: THEME.primary }} />
                          Token Usage Trend
                        </CardTitle>
                        <CardDescription style={{ color: THEME.textSecondary }}>
                          Daily token consumption over time
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <ResponsiveContainer width="100%" height={280}>
                          <AreaChart data={metrics.by_date}>
                            <defs>
                              <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor={THEME.primary} stopOpacity={0.3} />
                                <stop offset="100%" stopColor={THEME.primary} stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                            <XAxis
                              dataKey="date"
                              tick={{ fontSize: 12, fill: THEME.textSecondary }}
                              tickFormatter={(value) => value.slice(5)}
                              axisLine={{ stroke: '#e5e7eb' }}
                            />
                            <YAxis
                              tick={{ fontSize: 12, fill: THEME.textSecondary }}
                              tickFormatter={(value) => formatTokens(value)}
                              axisLine={{ stroke: '#e5e7eb' }}
                            />
                            <Tooltip content={<CustomTooltip />} />
                            <Area
                              type="monotone"
                              dataKey="total_tokens"
                              stroke={THEME.primary}
                              strokeWidth={2}
                              fill="url(#tokenGradient)"
                              name="Tokens"
                            />
                          </AreaChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  )}

                  {/* Model Usage Pie Chart */}
                  {metrics?.by_model && metrics.by_model.length > 0 && (
                    <Card className="border-0 shadow-sm">
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                          <PieChartIcon className="h-5 w-5" style={{ color: THEME.chartColors[1] }} />
                          Model Distribution
                        </CardTitle>
                        <CardDescription style={{ color: THEME.textSecondary }}>
                          Token usage breakdown by model
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <ResponsiveContainer width="100%" height={280}>
                          <PieChart>
                            <Pie
                              data={metrics.by_model.slice(0, 5)}
                              cx="50%"
                              cy="50%"
                              innerRadius={70}
                              outerRadius={100}
                              paddingAngle={3}
                              dataKey="total_tokens"
                              nameKey="model"
                            >
                              {metrics.by_model.slice(0, 5).map((_, index) => (
                                <Cell
                                  key={`cell-${index}`}
                                  fill={THEME.chartColors[index % THEME.chartColors.length]}
                                />
                              ))}
                            </Pie>
                            <Tooltip
                              formatter={(value: number) => formatTokens(value)}
                              contentStyle={{
                                backgroundColor: 'white',
                                border: '1px solid #e5e7eb',
                                borderRadius: '8px',
                                boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
                              }}
                            />
                            <Legend
                              formatter={(value) => (
                                <span style={{ color: THEME.textMain, fontSize: '12px' }}>
                                  {(value as string).split("/").pop() || value}
                                </span>
                              )}
                            />
                          </PieChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  )}
                </div>

                {/* Model Usage Summary */}
                {metrics?.by_model && metrics.by_model.length > 0 && (
                  <Card className="border-0 shadow-sm">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <Cpu className="h-5 w-5" style={{ color: THEME.chartColors[4] }} />
                        Model Usage Summary
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Table>
                        <TableHeader>
                          <TableRow className="border-gray-100">
                            <TableHead style={{ color: THEME.textSecondary }}>Model</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Calls</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Share</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {metrics.by_model.slice(0, 5).map((model, idx) => {
                            const totalTokens = metrics.by_model.reduce((sum, m) => sum + m.total_tokens, 0);
                            const share = totalTokens > 0 ? (model.total_tokens / totalTokens) * 100 : 0;

                            return (
                              <TableRow key={model.model} className="border-gray-100 hover:bg-gray-50">
                                <TableCell className="font-medium" style={{ color: THEME.textMain }}>
                                  <div className="flex items-center gap-2">
                                    <div
                                      className="w-3 h-3 rounded-full"
                                      style={{ backgroundColor: THEME.chartColors[idx % THEME.chartColors.length] }}
                                    />
                                    {model.model.split("/").pop() || model.model}
                                  </div>
                                </TableCell>
                                <TableCell className="text-right" style={{ color: THEME.textMain }}>{model.call_count}</TableCell>
                                <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(model.total_tokens)}</TableCell>
                                <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(model.total_cost)}</TableCell>
                                <TableCell className="text-right">
                                  <div className="flex items-center justify-end gap-2">
                                    <ProgressBar value={share} max={100} color={THEME.chartColors[idx % THEME.chartColors.length]} showLabel={false} />
                                    <span className="text-xs font-medium min-w-[40px]" style={{ color: THEME.textSecondary }}>
                                      {share.toFixed(1)}%
                                    </span>
                                  </div>
                                </TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>
                )}

                {/* Recent Sessions */}
                {sessionsData?.sessions && sessionsData.sessions.length > 0 && (
                  <Card className="border-0 shadow-sm">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <Clock className="h-5 w-5" style={{ color: THEME.chartColors[3] }} />
                        Recent Sessions
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {sessionsData.sessions.slice(0, 5).map((session) => (
                          <div
                            key={session.session_id}
                            className={`flex items-center justify-between p-4 rounded-lg cursor-pointer transition-all hover:shadow-md ${
                              session.has_errors
                                ? 'bg-red-50 border border-red-100'
                                : 'bg-gray-50 hover:bg-gray-100'
                            }`}
                            onClick={() => setSelectedSession(session.session_id)}
                          >
                            <div className="flex items-center gap-4">
                              <div
                                className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                                  session.has_errors ? 'bg-red-100' : 'bg-white'
                                }`}
                              >
                                {session.has_errors ? (
                                  <XCircle className="h-5 w-5 text-red-500" />
                                ) : (
                                  <Clock className="h-5 w-5" style={{ color: THEME.textSecondary }} />
                                )}
                              </div>
                              <div>
                                <p className="font-medium truncate max-w-[300px]" style={{ color: THEME.textMain }}>
                                  {session.session_id}
                                </p>
                                <p className="text-sm" style={{ color: THEME.textSecondary }}>
                                  {session.trace_count} traces | {formatTokens(session.total_tokens)} tokens
                                </p>
                              </div>
                            </div>
                            <div className="flex items-center gap-4">
                              <span className="text-sm font-medium" style={{ color: THEME.primary }}>
                                {formatCost(session.total_cost)}
                              </span>
                              <ChevronRight className="h-5 w-5" style={{ color: THEME.textSecondary }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            )}
          </TabsContent>

          {/* Agents Tab */}
          <TabsContent value="agents" className="space-y-4">
            {agentsData?.truncated && !fetchAllMode && (
              <TruncationBanner
                fetchedCount={agentsData.fetched_trace_count ?? 0}
                onLoadAll={() => setFetchAllMode(true)}
                isLoading={agentsLoading || agentsFetching}
              />
            )}
            {agentsTabLoading ? (
              <Skeleton className="h-64" />
            ) : (
              <Card className="border-0 shadow-sm">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <Bot className="h-5 w-5" style={{ color: THEME.primary }} />
                        Agents
                      </CardTitle>
                      <CardDescription style={{ color: THEME.textSecondary }}>
                        Your AI agents with usage metrics
                      </CardDescription>
                    </div>
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
                      <Input
                        placeholder="Search agents..."
                        value={agentSearch}
                        onChange={(e) => setAgentSearch(e.target.value)}
                        className="pl-9 h-9 w-64 bg-gray-50 border-gray-200"
                      />
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {filteredAgents.length > 0 ? (
                    <Table>
                      <TableHeader>
                        <TableRow className="border-gray-100">
                          <TableHead style={{ color: THEME.textSecondary }}>Agent</TableHead>
                          <TableHead style={{ color: THEME.textSecondary }}>Project</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Traces</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Sessions</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Status</TableHead>
                          <TableHead></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredAgents.map((agent) => (
                          <TableRow
                            key={agent.agent_id}
                            className="cursor-pointer border-gray-100 hover:bg-gray-50"
                            onClick={() => setSelectedAgent(agent.agent_id)}
                          >
                            <TableCell className="font-medium" style={{ color: THEME.textMain }}>
                              <div className="flex items-center gap-3">
                                <div
                                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                                  style={{ backgroundColor: `${THEME.primary}10` }}
                                >
                                  <Bot className="h-4 w-4" style={{ color: THEME.primary }} />
                                </div>
                                {agent.agent_name}
                              </div>
                            </TableCell>
                            <TableCell style={{ color: THEME.textSecondary }}>{agent.project_name || "-"}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{agent.trace_count ?? 0}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{agent.session_count ?? 0}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(agent.total_tokens ?? 0)}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(agent.total_cost ?? 0)}</TableCell>
                            <TableCell className="text-right">
                              {(agent.error_count ?? 0) > 0 ? (
                                <Badge style={{ backgroundColor: '#fee2e2', color: '#991b1b' }}>
                                  Error ({agent.error_count})
                                </Badge>
                              ) : (
                                <Badge style={{ backgroundColor: '#dcfce7', color: '#166534' }}>
                                  OK
                                </Badge>
                              )}
                            </TableCell>
                            <TableCell>
                              <ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <div className="text-center py-12">
                      <Bot className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
                      <p style={{ color: THEME.textSecondary }}>
                        {agentSearch ? `No agents found matching "${agentSearch}"` : "No agents found. Run a agent to see agent metrics."}
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Projects Tab */}
          <TabsContent value="projects" className="space-y-4">
            {projectsData?.truncated && !fetchAllMode && (
              <TruncationBanner
                fetchedCount={projectsData.fetched_trace_count ?? 0}
                onLoadAll={() => setFetchAllMode(true)}
                isLoading={projectsLoading || projectsFetching}
              />
            )}
            {projectsTabLoading ? (
              <Skeleton className="h-64" />
            ) : (
              <Card className="border-0 shadow-sm">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <FolderOpen className="h-5 w-5" style={{ color: THEME.chartColors[3] }} />
                        Projects
                      </CardTitle>
                      <CardDescription style={{ color: THEME.textSecondary }}>
                        Your projects with aggregated metrics
                      </CardDescription>
                    </div>
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
                      <Input
                        placeholder="Search projects..."
                        value={projectSearch}
                        onChange={(e) => setProjectSearch(e.target.value)}
                        className="pl-9 h-9 w-64 bg-gray-50 border-gray-200"
                      />
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {filteredProjects.length > 0 ? (
                    <Table>
                      <TableHeader>
                        <TableRow className="border-gray-100">
                          <TableHead style={{ color: THEME.textSecondary }}>Project</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Agents</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Traces</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Sessions</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                          <TableHead></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredProjects.map((project) => (
                          <TableRow
                            key={project.project_id}
                            className="cursor-pointer border-gray-100 hover:bg-gray-50"
                            onClick={() => setSelectedProject(project.project_id)}
                          >
                            <TableCell className="font-medium" style={{ color: THEME.textMain }}>
                              <div className="flex items-center gap-3">
                                <div
                                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                                  style={{ backgroundColor: `${THEME.chartColors[3]}15` }}
                                >
                                  <FolderOpen className="h-4 w-4" style={{ color: THEME.chartColors[3] }} />
                                </div>
                                {project.project_name}
                              </div>
                            </TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{project.agent_count ?? 0}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{project.trace_count ?? 0}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{project.session_count ?? 0}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(project.total_tokens ?? 0)}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(project.total_cost ?? 0)}</TableCell>
                            <TableCell>
                              <ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <div className="text-center py-12">
                      <FolderOpen className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
                      <p style={{ color: THEME.textSecondary }}>
                        {projectSearch ? `No projects found matching "${projectSearch}"` : "No projects found. Organize your agents into folders to see project metrics."}
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Sessions Tab */}
          <TabsContent value="sessions" className="space-y-4">
            {sessionsData?.truncated && !fetchAllMode && (
              <TruncationBanner
                fetchedCount={sessionsData.fetched_trace_count ?? 0}
                onLoadAll={() => setFetchAllMode(true)}
                isLoading={sessionsLoading || sessionsFetching}
              />
            )}
            {sessionsTabLoading ? (
              <Skeleton className="h-64" />
            ) : (
              <Card className="border-0 shadow-sm">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <Clock className="h-5 w-5" style={{ color: THEME.chartColors[1] }} />
                        Sessions
                      </CardTitle>
                      <CardDescription style={{ color: THEME.textSecondary }}>
                        Your chat sessions with metrics
                      </CardDescription>
                    </div>
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
                      <Input
                        placeholder="Search sessions..."
                        value={sessionSearch}
                        onChange={(e) => setSessionSearch(e.target.value)}
                        className="pl-9 h-9 w-64 bg-gray-50 border-gray-200"
                      />
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {filteredSessions.length > 0 ? (
                    <Table>
                      <TableHeader>
                        <TableRow className="border-gray-100">
                          <TableHead style={{ color: THEME.textSecondary }}>Session ID</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Traces</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                          <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Latency</TableHead>
                          <TableHead style={{ color: THEME.textSecondary }}>Models</TableHead>
                          <TableHead></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredSessions.map((session) => (
                          <TableRow
                            key={session.session_id}
                            className={`cursor-pointer border-gray-100 hover:bg-gray-50 ${
                              session.has_errors ? "bg-red-50/50" : ""
                            }`}
                            onClick={() => setSelectedSession(session.session_id)}
                          >
                            <TableCell className="font-medium max-w-[200px] truncate" style={{ color: THEME.textMain }}>
                              <div className="flex items-center gap-2">
                                {session.has_errors && <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />}
                                {session.session_id}
                              </div>
                            </TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{session.trace_count}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(session.total_tokens)}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(session.total_cost)}</TableCell>
                            <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatLatency(session.avg_latency_ms ?? null)}</TableCell>
                            <TableCell>
                              <div className="flex gap-1 flex-wrap">
                                {session.models_used.slice(0, 2).map((model) => (
                                  <Badge
                                    key={model}
                                    variant="secondary"
                                    className="text-xs bg-gray-100"
                                    style={{ color: THEME.textMain }}
                                  >
                                    {model.split("/").pop() || model}
                                  </Badge>
                                ))}
                                {session.models_used.length > 2 && (
                                  <Badge
                                    variant="secondary"
                                    className="text-xs bg-gray-100"
                                    style={{ color: THEME.textSecondary }}
                                  >
                                    +{session.models_used.length - 2}
                                  </Badge>
                                )}
                              </div>
                            </TableCell>
                            <TableCell>
                              <ChevronRight className="h-4 w-4" style={{ color: THEME.textSecondary }} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <div className="text-center py-12">
                      <Clock className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
                      <p style={{ color: THEME.textSecondary }}>
                        {sessionSearch ? `No sessions found matching "${sessionSearch}"` : "No sessions found"}
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Models Tab */}
          <TabsContent value="models" className="space-y-4">
            {metricsLoading ? (
              <Skeleton className="h-64" />
            ) : (
              <>
                <Card className="border-0 shadow-sm">
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <Cpu className="h-5 w-5" style={{ color: THEME.chartColors[4] }} />
                        Model Usage Breakdown
                      </CardTitle>
                      <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
                        <Input
                          placeholder="Search models..."
                          value={modelSearch}
                          onChange={(e) => setModelSearch(e.target.value)}
                          className="pl-9 h-9 w-64 bg-gray-50 border-gray-200"
                        />
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {filteredModels.length > 0 ? (
                      <Table>
                        <TableHeader>
                          <TableRow className="border-gray-100">
                            <TableHead style={{ color: THEME.textSecondary }}>Model</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Calls</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Input Tokens</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Output Tokens</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Total Tokens</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Avg Latency</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {filteredModels.map((model, idx) => (
                            <TableRow key={model.model} className="border-gray-100 hover:bg-gray-50">
                              <TableCell className="font-medium" style={{ color: THEME.textMain }}>
                                <div className="flex items-center gap-2">
                                  <div
                                    className="w-3 h-3 rounded-full"
                                    style={{ backgroundColor: THEME.chartColors[idx % THEME.chartColors.length] }}
                                  />
                                  {model.model}
                                </div>
                              </TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{model.call_count}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(model.input_tokens)}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(model.output_tokens)}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(model.total_tokens)}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(model.total_cost)}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatLatency(model.avg_latency_ms)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    ) : (
                      <div className="text-center py-12">
                        <Cpu className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
                        <p style={{ color: THEME.textSecondary }}>
                          {modelSearch ? `No models found matching "${modelSearch}"` : "No model usage data"}
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Top agents - Horizontal Bar Chart */}
                {metrics?.top_agents && metrics.top_agents.length > 0 && (
                  <Card className="border-0 shadow-sm">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <TrendingUp className="h-5 w-5" style={{ color: THEME.primary }} />
                        Top Agents by Usage
                      </CardTitle>
                      <CardDescription style={{ color: THEME.textSecondary }}>
                        agent execution count and token usage
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <ResponsiveContainer width="100%" height={Math.max(250, metrics.top_agents.length * 50)}>
                        <BarChart
                          data={metrics.top_agents.slice(0, 10).map(agent => ({
                            ...agent,
                            shortName: agent.name.length > 25 ? agent.name.slice(0, 25) + '...' : agent.name
                          }))}
                          layout="vertical"
                          margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={true} vertical={false} />
                          <XAxis
                            type="number"
                            tick={{ fontSize: 12, fill: THEME.textSecondary }}
                            axisLine={{ stroke: '#e5e7eb' }}
                          />
                          <YAxis
                            type="category"
                            dataKey="shortName"
                            width={150}
                            tick={{ fontSize: 11, fill: THEME.textMain }}
                            axisLine={{ stroke: '#e5e7eb' }}
                          />
                          <Tooltip
                            content={({ active, payload }) => {
                              if (!active || !payload || !payload.length) return null;
                              const data = payload[0].payload;
                              return (
                                <div className="bg-white border shadow-lg rounded-lg p-3">
                                  <p className="text-sm font-medium mb-2" style={{ color: THEME.textMain }}>{data.name}</p>
                                  <div className="space-y-1 text-sm">
                                    <div className="flex justify-between gap-4">
                                      <span style={{ color: THEME.textSecondary }}>Count:</span>
                                      <span className="font-medium" style={{ color: THEME.textMain }}>{data.count}</span>
                                    </div>
                                    <div className="flex justify-between gap-4">
                                      <span style={{ color: THEME.textSecondary }}>Tokens:</span>
                                      <span className="font-medium" style={{ color: THEME.textMain }}>{formatTokens(data.tokens)}</span>
                                    </div>
                                    <div className="flex justify-between gap-4">
                                      <span style={{ color: THEME.textSecondary }}>Cost:</span>
                                      <span className="font-medium" style={{ color: THEME.textMain }}>{formatCost(data.cost)}</span>
                                    </div>
                                  </div>
                                </div>
                              );
                            }}
                          />
                          <Legend />
                          <Bar
                            dataKey="count"
                            fill={THEME.primary}
                            name="Execution Count"
                            radius={[0, 4, 4, 0]}
                          />
                          <Bar
                            dataKey="tokens"
                            fill={THEME.chartColors[1]}
                            name="Tokens"
                            radius={[0, 4, 4, 0]}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    </CardContent>
                  </Card>
                )}
              </>
            )}
          </TabsContent>

          {/* Usage Tab */}
          <TabsContent value="usage" className="space-y-4">
            {metricsLoading ? (
              <Skeleton className="h-64" />
            ) : (
              <>
                {/* Usage Charts */}
                {metrics?.by_date && metrics.by_date.length > 0 && (
                  <div className="grid gap-4 md:grid-cols-2">
                    {/* Traces & Observations Bar Chart */}
                    <Card className="border-0 shadow-sm">
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                          <Activity className="h-5 w-5" style={{ color: THEME.primary }} />
                          Traces & Observations
                        </CardTitle>
                        <CardDescription style={{ color: THEME.textSecondary }}>
                          Daily activity breakdown
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <ResponsiveContainer width="100%" height={280}>
                          <BarChart data={metrics.by_date}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                            <XAxis
                              dataKey="date"
                              tick={{ fontSize: 12, fill: THEME.textSecondary }}
                              tickFormatter={(value) => value.slice(5)}
                              axisLine={{ stroke: '#e5e7eb' }}
                            />
                            <YAxis
                              tick={{ fontSize: 12, fill: THEME.textSecondary }}
                              axisLine={{ stroke: '#e5e7eb' }}
                            />
                            <Tooltip content={<CustomTooltip />} />
                            <Legend />
                            <Bar
                              dataKey="trace_count"
                              fill={THEME.primary}
                              name="Traces"
                              radius={[4, 4, 0, 0]}
                            />
                            <Bar
                              dataKey="observation_count"
                              fill={THEME.chartColors[1]}
                              name="Observations"
                              radius={[4, 4, 0, 0]}
                            />
                          </BarChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>

                    {/* Token Trend Area Chart */}
                    <Card className="border-0 shadow-sm">
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                          <Layers className="h-5 w-5" style={{ color: THEME.chartColors[2] }} />
                          Token Usage Trend
                        </CardTitle>
                        <CardDescription style={{ color: THEME.textSecondary }}>
                          Token breakdown over time
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <ResponsiveContainer width="100%" height={280}>
                          <AreaChart data={metrics.by_date}>
                            <defs>
                              <linearGradient id="usageTokenGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor={THEME.chartColors[2]} stopOpacity={0.3} />
                                <stop offset="100%" stopColor={THEME.chartColors[2]} stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                            <XAxis
                              dataKey="date"
                              tick={{ fontSize: 12, fill: THEME.textSecondary }}
                              tickFormatter={(value) => value.slice(5)}
                              axisLine={{ stroke: '#e5e7eb' }}
                            />
                            <YAxis
                              tick={{ fontSize: 12, fill: THEME.textSecondary }}
                              tickFormatter={(value) => formatTokens(value)}
                              axisLine={{ stroke: '#e5e7eb' }}
                            />
                            <Tooltip content={<CustomTooltip />} />
                            <Legend />
                            <Area
                              type="monotone"
                              dataKey="total_tokens"
                              stroke={THEME.chartColors[2]}
                              strokeWidth={2}
                              fill="url(#usageTokenGradient)"
                              name="Total Tokens"
                            />
                          </AreaChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  </div>
                )}

                {/* Daily Usage Table */}
                <Card className="border-0 shadow-sm">
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
                        <Calendar className="h-5 w-5" style={{ color: THEME.chartColors[3] }} />
                        Daily Usage Details
                      </CardTitle>
                      <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
                        <Input
                          placeholder="Search by date..."
                          value={usageSearch}
                          onChange={(e) => setUsageSearch(e.target.value)}
                          className="pl-9 h-9 w-64 bg-gray-50 border-gray-200"
                        />
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {filteredUsageData && filteredUsageData.length > 0 ? (
                      <Table>
                        <TableHeader>
                          <TableRow className="border-gray-100">
                            <TableHead style={{ color: THEME.textSecondary }}>Date</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Traces</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Observations</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Tokens</TableHead>
                            <TableHead className="text-right" style={{ color: THEME.textSecondary }}>Cost</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {filteredUsageData.map((day) => (
                            <TableRow key={day.date} className="border-gray-100 hover:bg-gray-50">
                              <TableCell className="font-medium" style={{ color: THEME.textMain }}>{day.date}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{day.trace_count}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{day.observation_count}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatTokens(day.total_tokens)}</TableCell>
                              <TableCell className="text-right" style={{ color: THEME.textMain }}>{formatCost(day.total_cost)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    ) : (
                      <div className="text-center py-12">
                        <Calendar className="h-12 w-12 mx-auto mb-4" style={{ color: THEME.textSecondary }} />
                        <p style={{ color: THEME.textSecondary }}>
                          {usageSearch ? `No results for "${usageSearch}"` : "No usage data"}
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </TabsContent>
        </Tabs>
      </div>

      {/* Session Detail Dialog */}
      <Dialog open={!!selectedSession} onOpenChange={() => setSelectedSession(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
              <Clock className="h-5 w-5" style={{ color: THEME.primary }} />
              Session Details
            </DialogTitle>
            <DialogDescription className="truncate" style={{ color: THEME.textSecondary }}>
              {selectedSession}
            </DialogDescription>
          </DialogHeader>
          {sessionDetailLoading || sessionDetailFetching ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <div
                className="animate-spin rounded-full h-8 w-8 border-2 border-gray-200"
                style={{ borderTopColor: THEME.primary }}
              />
              <p className="text-sm" style={{ color: THEME.textSecondary }}>Loading session details…</p>
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
                    <div
                      key={trace.id}
                      className="p-4 bg-gray-50 rounded-lg cursor-pointer hover:bg-gray-100 transition-colors"
                      onClick={() => setSelectedTrace(trace.id)}
                    >
                      <div className="flex justify-between items-center">
                        <div>
                          <p className="font-medium" style={{ color: THEME.textMain }}>{trace.name || trace.id}</p>
                          <p className="text-sm" style={{ color: THEME.textSecondary }}>
                            {formatDate(trace.timestamp)} | {formatTokens(trace.total_tokens)} tokens | {formatCost(trace.total_cost)}
                          </p>
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

      {/* Trace Detail Dialog */}
      <Dialog open={!!selectedTrace} onOpenChange={() => setSelectedTrace(null)}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
              <Activity className="h-5 w-5" style={{ color: THEME.primary }} />
              Trace Details
            </DialogTitle>
            <DialogDescription style={{ color: THEME.textSecondary }}>
              {traceDetail?.name || selectedTrace}
            </DialogDescription>
          </DialogHeader>
          {traceDetailLoading || traceDetailFetching ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <div
                className="animate-spin rounded-full h-8 w-8 border-2 border-gray-200"
                style={{ borderTopColor: THEME.primary }}
              />
              <p className="text-sm" style={{ color: THEME.textSecondary }}>Loading trace details…</p>
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
                  <div className="text-sm bg-gray-50 rounded-lg p-4" style={{ color: THEME.textSecondary }}>
                    No evaluation scores found for this trace.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {traceDetail.scores.map((score) => (
                      <div key={score.id} className="bg-gray-50 rounded-lg p-4 border border-gray-100">
                        <div className="flex justify-between items-center gap-4">
                          <div className="min-w-0">
                            <p className="font-medium truncate" style={{ color: THEME.textMain }}>{score.name}</p>
                            <p className="text-xs" style={{ color: THEME.textSecondary }}>
                              {score.source || "evaluator"}{score.created_at ? ` | ${formatDate(score.created_at)}` : ""}
                            </p>
                          </div>
                          <Badge variant="outline" className="font-semibold">
                            {Number.isFinite(score.value) ? score.value.toFixed(3) : score.value}
                          </Badge>
                        </div>
                        {score.comment && (
                          <p className="text-sm mt-2 whitespace-pre-wrap" style={{ color: THEME.textSecondary }}>
                            {score.comment}
                          </p>
                        )}
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
                      className={`p-4 rounded-lg border cursor-pointer transition-colors ${
                        obs.level === "ERROR"
                          ? "border-red-200 bg-red-50"
                          : "bg-gray-50 hover:bg-gray-100 border-gray-100"
                      }`}
                      onClick={() => setExpandedObservation(expandedObservation === obs.id ? null : obs.id)}
                    >
                      <div className="flex justify-between items-center">
                        <div className="flex items-center gap-2">
                          <Badge
                            style={{
                              backgroundColor: obs.type === "GENERATION" ? THEME.primary : '#e5e7eb',
                              color: obs.type === "GENERATION" ? 'white' : THEME.textMain,
                            }}
                          >
                            {obs.type || "SPAN"}
                          </Badge>
                          <span className="font-medium" style={{ color: THEME.textMain }}>
                            {obs.name || "Unnamed"}
                          </span>
                          {obs.model && (
                            <Badge variant="outline" className="text-xs">
                              {obs.model.split("/").pop() || obs.model}
                            </Badge>
                          )}
                        </div>
                        <div className="text-sm" style={{ color: THEME.textSecondary }}>
                          {formatTokens(obs.total_tokens)} tokens | {formatCost(obs.total_cost)} | {formatLatency(obs.latency_ms)}
                        </div>
                      </div>
                      {expandedObservation === obs.id && (
                        <div className="mt-3 pt-3 border-t border-gray-200 space-y-2">
                          {obs.input && (
                            <div>
                              <p className="text-sm font-medium mb-1" style={{ color: THEME.textMain }}>Input</p>
                              <pre className="text-xs bg-white p-3 rounded border overflow-auto max-h-32" style={{ color: THEME.textSecondary }}>
                                {JSON.stringify(obs.input, null, 2)}
                              </pre>
                            </div>
                          )}
                          {obs.output && (
                            <div>
                              <p className="text-sm font-medium mb-1" style={{ color: THEME.textMain }}>Output</p>
                              <pre className="text-xs bg-white p-3 rounded border overflow-auto max-h-32" style={{ color: THEME.textSecondary }}>
                                {JSON.stringify(obs.output, null, 2)}
                              </pre>
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
          ) : traceDetailError ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <AlertCircle className="h-10 w-10" style={{ color: THEME.error }} />
              <p className="text-sm font-semibold" style={{ color: THEME.textMain }}>Trace could not be loaded</p>
              <p className="text-xs text-center max-w-xs" style={{ color: THEME.textSecondary }}>
                The trace may have been deleted, or is not accessible in the current time range. Try widening the date filter.
              </p>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      {/* Agent Detail Dialog */}
      <Dialog open={!!selectedAgent} onOpenChange={() => setSelectedAgent(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
              <Bot className="h-5 w-5" style={{ color: THEME.primary }} />
              {agentDetail?.agent_name || "Agent Details"}
            </DialogTitle>
          </DialogHeader>
          {agentDetailLoading ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <div
                className="animate-spin rounded-full h-8 w-8 border-2 border-gray-200"
                style={{ borderTopColor: THEME.primary }}
              />
              <p className="text-sm" style={{ color: THEME.textSecondary }}>Loading agent details…</p>
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
                      className={`p-4 rounded-lg cursor-pointer transition-colors ${
                        session.has_errors
                          ? "bg-red-50 border border-red-200"
                          : "bg-gray-50 hover:bg-gray-100"
                      }`}
                      onClick={() => {
                        setSelectedAgent(null);
                        setSelectedSession(session.session_id);
                      }}
                    >
                      <div className="flex justify-between items-center">
                        <div>
                          <p className="font-medium truncate max-w-[300px]" style={{ color: THEME.textMain }}>
                            {session.session_id}
                          </p>
                          <p className="text-sm" style={{ color: THEME.textSecondary }}>
                            {session.trace_count} traces | {formatTokens(session.total_tokens)} tokens | {formatCost(session.total_cost)}
                          </p>
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

      {/* Project Detail Dialog */}
      <Dialog open={!!selectedProject} onOpenChange={() => setSelectedProject(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2" style={{ color: THEME.textMain }}>
              <FolderOpen className="h-5 w-5" style={{ color: THEME.chartColors[3] }} />
              {projectDetail?.project_name || "Project Details"}
            </DialogTitle>
            <DialogDescription style={{ color: THEME.textSecondary }}>
              {projectDetailLoading && !projectDetail ? "Loading…" : `${projectDetail?.agent_count ?? 0} agents`}
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
                    <div
                      key={agent.agent_id}
                      className="p-4 bg-gray-50 rounded-lg cursor-pointer hover:bg-gray-100 transition-colors"
                      onClick={() => {
                        setSelectedProject(null);
                        setSelectedAgent(agent.agent_id);
                      }}
                    >
                      <div className="flex justify-between items-center">
                        <div className="flex items-center gap-3">
                          <div
                            className="w-8 h-8 rounded-lg flex items-center justify-center"
                            style={{ backgroundColor: `${THEME.primary}10` }}
                          >
                            <Bot className="h-4 w-4" style={{ color: THEME.primary }} />
                          </div>
                          <div>
                            <p className="font-medium" style={{ color: THEME.textMain }}>{agent.agent_name}</p>
                            <p className="text-sm" style={{ color: THEME.textSecondary }}>
                              {agent.trace_count} traces | {agent.session_count} sessions | {formatTokens(agent.total_tokens)} tokens
                            </p>
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
    </div>
  );
}
