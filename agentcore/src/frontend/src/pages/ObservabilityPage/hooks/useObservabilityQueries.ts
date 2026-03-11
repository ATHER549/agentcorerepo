import { useQuery } from "@tanstack/react-query";
import type { FetchMetricsParams } from "../types";
import {
  fetchStatus,
  fetchScopeOptions,
  fetchMetrics,
  fetchSessions,
  fetchSessionDetail,
  fetchTraceDetail,
  fetchAgents,
  fetchAgentDetail,
  fetchProjects,
  fetchProjectDetail,
} from "../api";

const LIST_STALE_MS = 60_000;
const DETAIL_STALE_MS = 30_000;
const GC_MS = 5 * 60_000;

interface QueryConfig {
  dateParams: FetchMetricsParams;
  scopeParams: FetchMetricsParams;
  filters: { dateRange: string; search: string; models: string[] };
  fetchAllMode: boolean;
  activeTab: string;
  canRunScopedQueries: boolean;
  selectedSession: string | null;
  selectedTrace: string | null;
  selectedAgent: string | null;
  selectedProject: string | null;
  selectedOrgId: string | null;
  selectedDeptId: string | null;
  selectedEnvironment: string;
}

export function useObservabilityQueries(config: QueryConfig) {
  const {
    dateParams,
    scopeParams,
    filters,
    fetchAllMode,
    activeTab,
    canRunScopedQueries,
    selectedSession,
    selectedTrace,
    selectedAgent,
    selectedProject,
    selectedOrgId,
    selectedDeptId,
    selectedEnvironment,
  } = config;

  const includeModelBreakdown = activeTab === "models";
  const shouldFetchMetrics = activeTab === "overview" || activeTab === "models";
  const shouldFetchSessions = activeTab === "overview" || activeTab === "sessions" || !!selectedSession;
  const shouldFetchAgents = activeTab === "agents" || !!selectedAgent;
  const shouldFetchProjects = activeTab === "projects" || !!selectedProject;

  const status = useQuery({
    queryKey: ["langfuse-status"],
    queryFn: fetchStatus,
    staleTime: LIST_STALE_MS,
    gcTime: GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const scopeOptions = useQuery({
    queryKey: ["observability-scope-options"],
    queryFn: fetchScopeOptions,
    staleTime: LIST_STALE_MS,
    gcTime: GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const metrics = useQuery({
    queryKey: [
      "observability-metrics",
      filters.dateRange,
      filters.search,
      filters.models.join(","),
      fetchAllMode,
      includeModelBreakdown,
      selectedOrgId,
      selectedDeptId,
      selectedEnvironment,
    ],
    queryFn: () =>
      fetchMetrics({
        ...dateParams,
        ...scopeParams,
        search: filters.search || undefined,
        models: filters.models.length > 0 ? filters.models.join(",") : undefined,
        include_model_breakdown: includeModelBreakdown,
      }),
    enabled: canRunScopedQueries && shouldFetchMetrics,
    staleTime: LIST_STALE_MS,
    gcTime: GC_MS,
    placeholderData: (prev: any) => prev,
    refetchOnWindowFocus: false,
  });

  const sessionsData = useQuery({
    queryKey: ["observability-sessions", filters.dateRange, fetchAllMode, selectedOrgId, selectedDeptId, selectedEnvironment],
    queryFn: () => fetchSessions({ ...dateParams, ...scopeParams }),
    enabled: canRunScopedQueries && shouldFetchSessions,
    staleTime: LIST_STALE_MS,
    gcTime: GC_MS,
    placeholderData: (prev: any) => prev,
    refetchOnWindowFocus: false,
  });

  const agentsData = useQuery({
    queryKey: ["observability-agents", filters.dateRange, fetchAllMode, selectedOrgId, selectedDeptId, selectedEnvironment],
    queryFn: () => fetchAgents({ ...dateParams, ...scopeParams }),
    enabled: canRunScopedQueries && shouldFetchAgents,
    staleTime: LIST_STALE_MS,
    gcTime: GC_MS,
    placeholderData: (prev: any) => prev,
    refetchOnWindowFocus: false,
  });

  const projectsData = useQuery({
    queryKey: ["observability-projects", filters.dateRange, fetchAllMode, selectedOrgId, selectedDeptId, selectedEnvironment],
    queryFn: () => fetchProjects({ ...dateParams, ...scopeParams }),
    enabled: canRunScopedQueries && shouldFetchProjects,
    staleTime: LIST_STALE_MS,
    gcTime: GC_MS,
    placeholderData: (prev: any) => prev,
    refetchOnWindowFocus: false,
  });

  const sessionDetail = useQuery({
    queryKey: ["session-detail", selectedSession, filters.dateRange, selectedOrgId, selectedDeptId, selectedEnvironment],
    queryFn: () => fetchSessionDetail(selectedSession!, { ...dateParams, ...scopeParams }),
    enabled: !!selectedSession && canRunScopedQueries,
    staleTime: DETAIL_STALE_MS,
    gcTime: GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const traceDetail = useQuery({
    queryKey: ["trace-detail", selectedTrace, selectedOrgId, selectedDeptId, selectedEnvironment],
    queryFn: () => fetchTraceDetail(selectedTrace!, scopeParams),
    enabled: !!selectedTrace && canRunScopedQueries,
    staleTime: DETAIL_STALE_MS,
    gcTime: GC_MS,
    retry: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const agentDetail = useQuery({
    queryKey: ["agent-detail", selectedAgent, filters.dateRange, selectedOrgId, selectedDeptId, selectedEnvironment],
    queryFn: () => fetchAgentDetail(selectedAgent!, { ...dateParams, ...scopeParams }),
    enabled: !!selectedAgent && canRunScopedQueries,
    staleTime: DETAIL_STALE_MS,
    gcTime: GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const projectDetail = useQuery({
    queryKey: ["project-detail", selectedProject, filters.dateRange, fetchAllMode, selectedOrgId, selectedDeptId, selectedEnvironment],
    queryFn: () => fetchProjectDetail(selectedProject!, { ...dateParams, ...scopeParams }),
    enabled: !!selectedProject && canRunScopedQueries,
    staleTime: DETAIL_STALE_MS,
    gcTime: GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const anyFetching =
    metrics.isFetching || sessionsData.isFetching || agentsData.isFetching || projectsData.isFetching;

  return {
    status,
    scopeOptions,
    metrics,
    sessionsData,
    agentsData,
    projectsData,
    sessionDetail,
    traceDetail,
    agentDetail,
    projectDetail,
    anyFetching,
    shouldFetchMetrics,
    shouldFetchSessions,
    shouldFetchAgents,
    shouldFetchProjects,
  };
}
