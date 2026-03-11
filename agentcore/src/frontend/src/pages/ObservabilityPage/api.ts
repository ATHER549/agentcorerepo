import { api } from "@/controllers/API/api";
import { getUserTimezoneOffset } from "./utils";
import type {
  LangfuseStatus,
  ScopeOptionsResponse,
  Metrics,
  SessionsResponse,
  SessionDetailResponse,
  TraceDetailResponse,
  AgentsResponse,
  AgentDetailResponse,
  ProjectsResponse,
  ProjectDetailResponse,
  FetchMetricsParams,
} from "./types";

function applyScopeParams(searchParams: URLSearchParams, params: FetchMetricsParams): void {
  if (params.org_id) searchParams.set("org_id", params.org_id);
  if (params.dept_id) searchParams.set("dept_id", params.dept_id);
  if (params.environment) searchParams.set("environment", params.environment);
}

export async function fetchStatus(): Promise<LangfuseStatus> {
  const response = await api.get<LangfuseStatus>("/api/observability/status");
  return response.data;
}

export async function fetchScopeOptions(): Promise<ScopeOptionsResponse> {
  const response = await api.get<ScopeOptionsResponse>("/api/observability/scope-options");
  return response.data;
}

export async function fetchMetrics(params: FetchMetricsParams = {}): Promise<Metrics> {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  if (params.search) searchParams.set("search", params.search);
  if (params.models) searchParams.set("models", params.models);
  if (params.include_model_breakdown) searchParams.set("include_model_breakdown", "true");
  applyScopeParams(searchParams, params);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.fetch_all) searchParams.set("fetch_all", "true");
  const response = await api.get<Metrics>(`/api/observability/metrics?${searchParams.toString()}`);
  return response.data;
}

export async function fetchSessions(params: FetchMetricsParams = {}): Promise<SessionsResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("limit", "50");
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  applyScopeParams(searchParams, params);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.fetch_all) searchParams.set("fetch_all", "true");
  const response = await api.get<SessionsResponse>(`/api/observability/sessions?${searchParams.toString()}`);
  return response.data;
}

export async function fetchSessionDetail(sessionId: string, params: FetchMetricsParams = {}): Promise<SessionDetailResponse> {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  applyScopeParams(searchParams, params);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  const query = searchParams.toString();
  const response = await api.get<SessionDetailResponse>(`/api/observability/sessions/${encodeURIComponent(sessionId)}${query ? `?${query}` : ""}`);
  return response.data;
}

export async function fetchTraceDetail(traceId: string, params: FetchMetricsParams = {}): Promise<TraceDetailResponse> {
  const searchParams = new URLSearchParams();
  applyScopeParams(searchParams, params);
  const query = searchParams.toString();
  const response = await api.get<TraceDetailResponse>(`/api/observability/traces/${traceId}${query ? `?${query}` : ""}`);
  return response.data;
}

export async function fetchAgents(params: FetchMetricsParams = {}): Promise<AgentsResponse> {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  if (params.search) searchParams.set("search", params.search);
  applyScopeParams(searchParams, params);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.fetch_all) searchParams.set("fetch_all", "true");
  const queryString = searchParams.toString();
  const response = await api.get<AgentsResponse>(queryString ? `/api/observability/agents?${queryString}` : "/api/observability/agents");
  return response.data;
}

export async function fetchAgentDetail(agentId: string, params: FetchMetricsParams = {}): Promise<AgentDetailResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  applyScopeParams(searchParams, params);
  if (params.fetch_all) searchParams.set("fetch_all", "true");
  const response = await api.get<AgentDetailResponse>(`/api/observability/agents/${agentId}?${searchParams.toString()}`);
  return response.data;
}

export async function fetchProjects(params: FetchMetricsParams = {}): Promise<ProjectsResponse> {
  const searchParams = new URLSearchParams();
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  applyScopeParams(searchParams, params);
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.fetch_all) searchParams.set("fetch_all", "true");
  const queryString = searchParams.toString();
  const response = await api.get<ProjectsResponse>(queryString ? `/api/observability/projects?${queryString}` : "/api/observability/projects");
  return response.data;
}

export async function fetchProjectDetail(projectId: string, params: FetchMetricsParams = {}): Promise<ProjectDetailResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("tz_offset", String(params.tz_offset ?? getUserTimezoneOffset()));
  if (params.from_date) searchParams.set("from_date", params.from_date);
  if (params.to_date) searchParams.set("to_date", params.to_date);
  applyScopeParams(searchParams, params);
  if (params.fetch_all) searchParams.set("fetch_all", "true");
  const response = await api.get<ProjectDetailResponse>(`/api/observability/projects/${projectId}?${searchParams.toString()}`);
  return response.data;
}
