import { useState, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
    fetchAllMode, setFetchAllMode,
    traceScope, hasTraceScopeToggle, isDeptAdmin, isSuperAdmin, showDeptFilter,
    dateParams, scopeParams,
    roleKnown, requiresFilterFirst, scopeReady,
    isProvisioningAdminSessionRole, availableScopeDepartments,
    handleDateRangeChange, handleSearch, handleEnvironmentChange,
    handleTraceScopeChange,
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
    traceScope,
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
      <div className="flex h-full w-full flex-col overflow-auto bg-background p-6">
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
      <div className="flex h-full w-full flex-col overflow-auto bg-background p-6">
        <h1 className="text-2xl font-bold mb-6 text-foreground">{t("Observability")}</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t("Langfuse Not Connected")}</AlertTitle>
          <AlertDescription>
            {initialQueries.status.data?.message || t("Unable to connect to Langfuse. Please configure LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST environment variables.")}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-auto bg-background">
      {/* Header */}
      <div className="border-b bg-card px-4 py-3 shadow-sm sm:px-6 md:px-8 md:py-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <BarChart3 className="h-6 w-6 md:h-7 md:w-7" style={{ color: THEME.primary }} />
            <div>
              <h1 className="text-lg font-semibold md:text-xl text-foreground">{t("Observability")}</h1>
              <p className="text-sm text-muted-foreground">{t("Monitor your AI usage, costs, and performance metrics")}</p>
            </div>
          </div>

          {/* Environment Toggle */}
          <div className="flex items-center rounded-lg border border-border bg-muted/50 p-1">
            {([
              { value: "uat" as const, label: "UAT" },
              { value: "production" as const, label: "PROD" },
            ]).map((env) => (
              <button
                key={env.value}
                onClick={() => { if (selectedEnvironment !== env.value) handleEnvChange(env.value); }}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${selectedEnvironment === env.value ? "shadow-sm text-white" : "text-muted-foreground hover:bg-muted"}`}
                style={selectedEnvironment === env.value ? { backgroundColor: THEME.primary } : undefined}
              >
                {env.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-auto p-4 space-y-4 sm:p-6 sm:space-y-6">
        {!initialQueries.status.data?.connected && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t("Langfuse Not Connected")}</AlertTitle>
          <AlertDescription>{initialQueries.status.data?.message || t("Unable to connect to Langfuse for the selected scope.")}</AlertDescription>
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
          traceScope={traceScope}
          hasTraceScopeToggle={hasTraceScopeToggle}
          isDeptAdmin={isDeptAdmin}
          isSuperAdmin={isSuperAdmin}
          showDeptFilter={showDeptFilter}
          onDateRangeChange={handleDateRangeChange}
          onSearch={handleSearch}
          onModelChange={(models) => setFilters(prev => ({ ...prev, models }))}
          onOrgChange={handleOrgChangeWithClear}
          onDeptChange={handleDeptChangeWithClear}
          onTraceScopeChange={handleTraceScopeChange}
          onClearFilters={clearFilters}
          onClearScope={handleClearScopeWithClear}
          onRefresh={() => void handleManualRefresh()}
          isRefreshing={isManualRefreshing}
          isLoading={initialQueries.status.isLoading || initialQueries.scopeOptions.isLoading}
          isFetching={anyFetching}
        />

        {requiresFilterFirst && !scopeReady && (
          <Alert className="border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950/30">
            <AlertCircle className="h-4 w-4 text-blue-500" />
            <AlertTitle className="text-foreground">{t("Scope Required")}</AlertTitle>
            <AlertDescription className="text-muted-foreground">
              {t("Select an organization or department scope to load observability data.")}
            </AlertDescription>
          </Alert>
        )}

        {showScopeWarning && scopeWarningMessage && (
          <Alert className="border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30">
            <AlertCircle className="h-4 w-4 text-amber-500" />
            <AlertTitle className="text-foreground">{t("Observability Scope Warning")}</AlertTitle>
            <AlertDescription className="text-muted-foreground">{scopeWarningMessage}</AlertDescription>
          </Alert>
        )}

        {canRunScopedQueries && (
          <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
            <TabsList className="bg-card border shadow-sm p-1 rounded-lg">
              {[
                { value: "overview", label: t("Overview"), icon: BarChart3 },
                { value: "agents", label: t("Agents"), icon: Bot },
                { value: "projects", label: t("Projects"), icon: FolderOpen },
                { value: "sessions", label: t("Sessions"), icon: Clock },
                { value: "models", label: t("Models"), icon: Cpu },
                { value: "usage", label: t("Usage"), icon: Activity },
              ].map((tab) => (
                <TabsTrigger
                  key={tab.value}
                  value={tab.value}
                  className={`flex items-center gap-2 data-[state=active]:shadow-sm px-4 ${activeTab === tab.value ? "" : "text-muted-foreground"}`}
                  style={activeTab === tab.value ? { color: THEME.primary } : undefined}
                >
                  <tab.icon className="h-4 w-4" />
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>

            <TabsContent value="overview">
              {activeTab === "overview" && (
                <OverviewTab
                  metrics={metrics.data}
                  metricsLoading={metrics.isLoading}
                  metricsFetching={metrics.isFetching}
                  agentsData={agentsData.data}
                  sessionsData={sessionsData.data}
                  fetchAllMode={fetchAllMode}
                  onLoadAll={() => setFetchAllMode(true)}
                  onSelectSession={setSelectedSession}
                />
              )}
            </TabsContent>

            <TabsContent value="agents">
              {activeTab === "agents" && (
                <AgentsTab
                  agentsData={agentsData.data}
                  agentsLoading={agentsData.isLoading}
                  agentsFetching={agentsData.isFetching}
                  fetchAllMode={fetchAllMode}
                  onLoadAll={() => setFetchAllMode(true)}
                  onSelectAgent={setSelectedAgent}
                />
              )}
            </TabsContent>

            <TabsContent value="projects">
              {activeTab === "projects" && (
                <ProjectsTab
                  projectsData={projectsData.data}
                  projectsLoading={projectsData.isLoading}
                  projectsFetching={projectsData.isFetching}
                  fetchAllMode={fetchAllMode}
                  onLoadAll={() => setFetchAllMode(true)}
                  onSelectProject={setSelectedProject}
                />
              )}
            </TabsContent>

            <TabsContent value="sessions">
              {activeTab === "sessions" && (
                <SessionsTab
                  sessionsData={sessionsData.data}
                  sessionsLoading={sessionsData.isLoading}
                  sessionsFetching={sessionsData.isFetching}
                  fetchAllMode={fetchAllMode}
                  onLoadAll={() => setFetchAllMode(true)}
                  onSelectSession={setSelectedSession}
                />
              )}
            </TabsContent>

            <TabsContent value="models">
              {activeTab === "models" && (
                <ModelsTab
                  metrics={metrics.data}
                  metricsLoading={metrics.isLoading}
                  metricsFetching={metrics.isFetching}
                />
              )}
            </TabsContent>

            <TabsContent value="usage">
              {activeTab === "usage" && (
                <UsageTab
                  metrics={metrics.data}
                  metricsLoading={metrics.isLoading}
                  metricsFetching={metrics.isFetching}
                />
              )}
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
