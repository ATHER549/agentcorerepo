import { useState, useCallback, useMemo } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertCircle, BarChart3, Bot, FolderOpen, Clock, Cpu, Activity,
} from "lucide-react";
import { THEME } from "./theme";
import type { LangfuseEnvironment } from "./types";
import { useObservabilityFilters } from "./hooks/useObservabilityFilters";
import { useObservabilityQueries } from "./hooks/useObservabilityQueries";
import { FilterBar } from "./components/FilterBar";
import { OverviewTab } from "./components/OverviewTab";
import { AgentsTab } from "./components/AgentsTab";
import { ProjectsTab } from "./components/ProjectsTab";
import { SessionsTab } from "./components/SessionsTab";
import { ModelsTab } from "./components/ModelsTab";
import { UsageTab } from "./components/UsageTab";
import {
  SessionDetailDialog, TraceDetailDialog,
  AgentDetailDialog, ProjectDetailDialog,
} from "./components/DetailDialogs";

export default function ObservabilityPage(): JSX.Element {
  // Detail modal selections
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [isManualRefreshing, setIsManualRefreshing] = useState(false);

  // Initial query for scope options (needed before filters can be configured)
  const initialQueries = useObservabilityQueries({
    dateParams: {},
    scopeParams: {},
    filters: { dateRange: "today", search: "", models: [] },
    fetchAllMode: false,
    activeTab: "overview",
    canRunScopedQueries: false,
    selectedSession: null,
    selectedTrace: null,
    selectedAgent: null,
    selectedProject: null,
    selectedOrgId: null,
    selectedDeptId: null,
    selectedEnvironment: "uat",
  });

  const filtersHook = useObservabilityFilters(initialQueries.scopeOptions.data);
  const {
    filters, setFilters, searchInput, setSearchInput,
    selectedEnvironment, selectedOrgId, selectedDeptId,
    fetchAllMode, setFetchAllMode, dateParams, scopeParams,
    roleKnown, requiresFilterFirst, scopeReady,
    isProvisioningAdminSessionRole, availableScopeDepartments,
    handleDateRangeChange, handleSearch, handleEnvironmentChange,
    handleOrgChange, handleDeptChange, clearFilters, clearScope,
  } = filtersHook;

  const canRunScopedQueries = !!initialQueries.status.data?.connected && roleKnown && scopeReady;

  const queries = useObservabilityQueries({
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
  });

  const {
    status, scopeOptions, metrics, sessionsData, agentsData, projectsData,
    sessionDetail, traceDetail, agentDetail, projectDetail,
    anyFetching,
  } = queries;

  // Scope warning
  const scopeWarningMessage = useMemo(() => {
    const candidates = [
      metrics.data?.scope_warning_message,
      sessionsData.data?.scope_warning_message,
      agentsData.data?.scope_warning_message,
      projectsData.data?.scope_warning_message,
    ];
    return candidates.find(Boolean) ?? null;
  }, [metrics.data, sessionsData.data, agentsData.data, projectsData.data]);

  const showScopeWarning = Boolean(
    metrics.data?.scope_warning || sessionsData.data?.scope_warning ||
    agentsData.data?.scope_warning || projectsData.data?.scope_warning,
  );

  // Clear selections on environment/scope changes
  const clearSelections = useCallback(() => {
    setSelectedSession(null);
    setSelectedTrace(null);
    setSelectedAgent(null);
    setSelectedProject(null);
  }, []);

  const handleEnvChange = useCallback((env: LangfuseEnvironment) => {
    handleEnvironmentChange(env);
    clearSelections();
  }, [handleEnvironmentChange, clearSelections]);

  const handleOrgChangeWithClear = useCallback((orgId: string) => {
    handleOrgChange(orgId);
    clearSelections();
  }, [handleOrgChange, clearSelections]);

  const handleDeptChangeWithClear = useCallback((deptId: string) => {
    handleDeptChange(deptId);
    clearSelections();
  }, [handleDeptChange, clearSelections]);

  const handleClearScopeWithClear = useCallback(() => {
    clearScope();
    clearSelections();
  }, [clearScope, clearSelections]);

  const handleManualRefresh = useCallback(async () => {
    setIsManualRefreshing(true);
    try {
      const tasks: Promise<unknown>[] = [status.refetch(), scopeOptions.refetch()];
      if (canRunScopedQueries) {
        tasks.push(metrics.refetch(), sessionsData.refetch(), agentsData.refetch(), projectsData.refetch());
      }
      await Promise.all(tasks);
    } finally {
      setIsManualRefreshing(false);
    }
  }, [canRunScopedQueries, status, scopeOptions, metrics, sessionsData, agentsData, projectsData]);

  // Loading state
  if (initialQueries.status.isLoading) {
    return (
      <div className="flex h-full w-full flex-col overflow-auto bg-gray-50 p-6">
        <Skeleton className="h-8 w-48 mb-6" />
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-32" />)}
        </div>
      </div>
    );
  }

  // Not connected state
  if (!initialQueries.status.data?.connected && !isProvisioningAdminSessionRole) {
    return (
      <div className="flex h-full w-full flex-col overflow-auto bg-gray-50 p-6">
        <h1 className="text-2xl font-bold mb-6" style={{ color: THEME.textMain }}>Observability</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Langfuse Not Connected</AlertTitle>
          <AlertDescription>
            {initialQueries.status.data?.message || "Unable to connect to Langfuse. Please configure LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST environment variables."}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-auto bg-gray-50">
      {/* Header */}
      <div className="border-b bg-white px-8 py-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BarChart3 className="h-7 w-7" style={{ color: THEME.primary }} />
            <div>
              <h1 className="text-2xl font-semibold" style={{ color: THEME.textMain }}>Observability</h1>
              <p className="text-sm" style={{ color: THEME.textSecondary }}>Monitor your AI usage, costs, and performance metrics</p>
            </div>
          </div>

          {/* Environment Toggle */}
          <div className="flex items-center rounded-lg border bg-gray-50 p-1">
            {([
              { value: "uat" as const, label: "UAT" },
              { value: "production" as const, label: "PROD" },
            ]).map((env) => (
              <button
                key={env.value}
                onClick={() => { if (selectedEnvironment !== env.value) handleEnvChange(env.value); }}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${selectedEnvironment === env.value ? "shadow-sm" : "hover:bg-gray-100"}`}
                style={selectedEnvironment === env.value ? { backgroundColor: THEME.primary, color: "#fff" } : { color: THEME.textSecondary }}
              >
                {env.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-auto p-6 space-y-6">
        {!initialQueries.status.data?.connected && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Langfuse Not Connected</AlertTitle>
            <AlertDescription>{initialQueries.status.data?.message || "Unable to connect to Langfuse for the selected scope."}</AlertDescription>
          </Alert>
        )}

        <FilterBar
          filters={filters}
          searchInput={searchInput}
          setSearchInput={setSearchInput}
          selectedEnvironment={selectedEnvironment}
          selectedOrgId={selectedOrgId}
          selectedDeptId={selectedDeptId}
          scopeOptions={scopeOptions.data}
          availableScopeDepartments={availableScopeDepartments}
          metrics={metrics.data}
          onDateRangeChange={handleDateRangeChange}
          onSearch={handleSearch}
          onModelChange={(models) => setFilters(prev => ({ ...prev, models }))}
          onOrgChange={handleOrgChangeWithClear}
          onDeptChange={handleDeptChangeWithClear}
          onClearFilters={clearFilters}
          onClearScope={handleClearScopeWithClear}
          onRefresh={() => void handleManualRefresh()}
          isRefreshing={isManualRefreshing}
          isLoading={initialQueries.status.isLoading || initialQueries.scopeOptions.isLoading}
          isFetching={anyFetching}
        />

        {requiresFilterFirst && !scopeReady && (
          <Alert className="border-blue-200 bg-blue-50">
            <AlertCircle className="h-4 w-4" style={{ color: THEME.info }} />
            <AlertTitle style={{ color: THEME.textMain }}>Scope Required</AlertTitle>
            <AlertDescription style={{ color: THEME.textSecondary }}>
              Select an organization or department scope to load observability data.
            </AlertDescription>
          </Alert>
        )}

        {showScopeWarning && scopeWarningMessage && (
          <Alert className="border-amber-200 bg-amber-50">
            <AlertCircle className="h-4 w-4" style={{ color: THEME.warning }} />
            <AlertTitle style={{ color: THEME.textMain }}>Observability Scope Warning</AlertTitle>
            <AlertDescription style={{ color: THEME.textSecondary }}>{scopeWarningMessage}</AlertDescription>
          </Alert>
        )}

        {canRunScopedQueries && (
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
                  style={{ color: activeTab === tab.value ? THEME.primary : THEME.textSecondary }}
                >
                  <tab.icon className="h-4 w-4" />
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>

            <TabsContent value="overview">
              <OverviewTab
                metrics={metrics.data}
                metricsLoading={metrics.isLoading}
                agentsData={agentsData.data}
                sessionsData={sessionsData.data}
                fetchAllMode={fetchAllMode}
                onLoadAll={() => setFetchAllMode(true)}
                onSelectSession={setSelectedSession}
              />
            </TabsContent>

            <TabsContent value="agents">
              <AgentsTab
                agentsData={agentsData.data}
                agentsLoading={agentsData.isLoading}
                agentsFetching={agentsData.isFetching}
                fetchAllMode={fetchAllMode}
                onLoadAll={() => setFetchAllMode(true)}
                onSelectAgent={setSelectedAgent}
              />
            </TabsContent>

            <TabsContent value="projects">
              <ProjectsTab
                projectsData={projectsData.data}
                projectsLoading={projectsData.isLoading}
                projectsFetching={projectsData.isFetching}
                fetchAllMode={fetchAllMode}
                onLoadAll={() => setFetchAllMode(true)}
                onSelectProject={setSelectedProject}
              />
            </TabsContent>

            <TabsContent value="sessions">
              <SessionsTab
                sessionsData={sessionsData.data}
                sessionsLoading={sessionsData.isLoading}
                sessionsFetching={sessionsData.isFetching}
                fetchAllMode={fetchAllMode}
                onLoadAll={() => setFetchAllMode(true)}
                onSelectSession={setSelectedSession}
              />
            </TabsContent>

            <TabsContent value="models">
              <ModelsTab metrics={metrics.data} metricsLoading={metrics.isLoading} />
            </TabsContent>

            <TabsContent value="usage">
              <UsageTab metrics={metrics.data} metricsLoading={metrics.isLoading} />
            </TabsContent>
          </Tabs>
        )}
      </div>

      {/* Detail Dialogs */}
      <SessionDetailDialog
        selectedSession={selectedSession}
        onClose={() => setSelectedSession(null)}
        sessionDetail={sessionDetail.data}
        isLoading={sessionDetail.isLoading}
        isFetching={sessionDetail.isFetching}
        onSelectTrace={setSelectedTrace}
      />
      <TraceDetailDialog
        selectedTrace={selectedTrace}
        onClose={() => setSelectedTrace(null)}
        traceDetail={traceDetail.data}
        isLoading={traceDetail.isLoading}
        isFetching={traceDetail.isFetching}
        isError={traceDetail.isError}
      />
      <AgentDetailDialog
        selectedAgent={selectedAgent}
        onClose={() => setSelectedAgent(null)}
        agentDetail={agentDetail.data}
        isLoading={agentDetail.isLoading}
        onSelectSession={setSelectedSession}
      />
      <ProjectDetailDialog
        selectedProject={selectedProject}
        onClose={() => setSelectedProject(null)}
        projectDetail={projectDetail.data}
        isLoading={projectDetail.isLoading}
        onSelectAgent={setSelectedAgent}
      />
    </div>
  );
}
