export type DateRangePreset = "today" | "7d" | "30d" | "90d" | "all";
export type LangfuseEnvironment = "uat" | "production";

export interface Filters {
  dateRange: DateRangePreset;
  search: string;
  models: string[];
}

export interface LangfuseStatus {
  connected: boolean;
  host: string | null;
  message: string;
}

export interface ModelUsageItem {
  model: string;
  call_count: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  avg_latency_ms: number | null;
}

export interface DailyUsageItem {
  date: string;
  trace_count: number;
  observation_count: number;
  total_tokens: number;
  total_cost: number;
}

export interface Metrics {
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
  scope_warning?: boolean;
  scope_warning_message?: string | null;
}

export interface SessionListItem {
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

export interface TraceListItem {
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

export interface ObservationResponse {
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

export interface ScoreItem {
  id: string;
  name: string;
  value: number;
  source?: string | null;
  comment?: string | null;
  created_at?: string | null;
}

export interface TraceDetailResponse {
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
  scope_warning?: boolean;
  scope_warning_message?: string | null;
}

export interface SessionDetailResponse {
  session_id: string;
  trace_count: number;
  total_tokens: number;
  total_cost: number;
  first_trace_at: string | null;
  last_trace_at: string | null;
  models_used: Record<string, Record<string, unknown>>;
  traces: TraceListItem[];
  scope_warning?: boolean;
  scope_warning_message?: string | null;
}

export interface AgentListItem {
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

export interface AgentDetailResponse {
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
  scope_warning?: boolean;
  scope_warning_message?: string | null;
}

export interface ProjectListItem {
  project_id: string;
  project_name: string;
  agent_count: number;
  trace_count: number;
  session_count: number;
  total_tokens: number;
  total_cost: number;
  last_activity: string | null;
}

export interface ProjectDetailResponse {
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
  scope_warning?: boolean;
  scope_warning_message?: string | null;
}

export interface ScopeOptionItem {
  id: string;
  name: string;
}

export interface DepartmentScopeOption {
  id: string;
  name: string;
  org_id: string;
}

export interface ScopeOptionsResponse {
  role: string;
  requires_filter_first: boolean;
  organizations: ScopeOptionItem[];
  departments: DepartmentScopeOption[];
}

export interface SessionsResponse {
  sessions: SessionListItem[];
  total: number;
  truncated?: boolean;
  fetched_trace_count?: number;
  scope_warning?: boolean;
  scope_warning_message?: string | null;
}

export interface AgentsResponse {
  agents: AgentListItem[];
  total: number;
  truncated?: boolean;
  fetched_trace_count?: number;
  scope_warning?: boolean;
  scope_warning_message?: string | null;
}

export interface ProjectsResponse {
  projects: ProjectListItem[];
  total: number;
  truncated?: boolean;
  fetched_trace_count?: number;
  scope_warning?: boolean;
  scope_warning_message?: string | null;
}

export interface FetchMetricsParams {
  from_date?: string;
  to_date?: string;
  search?: string;
  models?: string;
  include_model_breakdown?: boolean;
  tz_offset?: number;
  fetch_all?: boolean;
  org_id?: string;
  dept_id?: string;
  environment?: LangfuseEnvironment;
}
