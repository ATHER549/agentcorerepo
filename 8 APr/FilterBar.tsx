import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Calendar, X, Cpu, RefreshCw } from "lucide-react";
import { THEME } from "../theme";
import { DATE_RANGE_LABELS } from "../utils";
import type {
  Filters, DateRangePreset, LangfuseEnvironment,
  ScopeOptionsResponse, DepartmentScopeOption, Metrics,
} from "../types";
import type { TraceScope } from "../hooks/useObservabilityFilters";

interface FilterBarProps {
  filters: Filters;
  searchInput: string;
  setSearchInput: (v: string) => void;
  selectedEnvironment: LangfuseEnvironment;
  selectedOrgId: string | null;
  selectedDeptId: string | null;
  scopeOptions: ScopeOptionsResponse | undefined;
  availableScopeDepartments: DepartmentScopeOption[];
  metrics: Metrics | undefined;
  traceScope: TraceScope;
  hasTraceScopeToggle: boolean;
  isDeptAdmin: boolean;
  isSuperAdmin: boolean;
  showDeptFilter: boolean;
  onDateRangeChange: (v: DateRangePreset) => void;
  onSearch: () => void;
  onModelChange: (models: string[]) => void;
  onOrgChange: (orgId: string) => void;
  onDeptChange: (deptId: string) => void;
  onTraceScopeChange: (scope: TraceScope) => void;
  onClearFilters: () => void;
  onClearScope: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  isLoading: boolean;
  isFetching: boolean;
}

const DEPT_ADMIN_SCOPE_OPTIONS: { value: TraceScope; label: string }[] = [
  { value: "all", label: "Dept Traces" },
  { value: "my", label: "My Traces" },
];

const SUPER_ADMIN_SCOPE_OPTIONS: { value: TraceScope; label: string }[] = [
  { value: "all", label: "Org Traces" },
  { value: "dept", label: "Dept Traces" },
  { value: "my", label: "My Traces" },
];

export function FilterBar({
  filters, searchInput, setSearchInput,
  selectedEnvironment, selectedOrgId, selectedDeptId,
  scopeOptions, availableScopeDepartments, metrics,
  traceScope, hasTraceScopeToggle, isDeptAdmin, isSuperAdmin, showDeptFilter,
  onDateRangeChange, onSearch, onModelChange,
  onOrgChange, onDeptChange, onTraceScopeChange, onClearFilters, onClearScope,
  onRefresh, isRefreshing, isLoading, isFetching,
}: FilterBarProps) {
  const availableModels = useMemo(() => metrics?.by_model?.map(m => m.model) || [], [metrics?.by_model]);
  const scopeToggleOptions = isSuperAdmin ? SUPER_ADMIN_SCOPE_OPTIONS : isDeptAdmin ? DEPT_ADMIN_SCOPE_OPTIONS : [];

  return (
    <div className="flex flex-wrap items-center gap-3 p-4 bg-card rounded-xl border border-border shadow-sm">
      {/* Date Range */}
      <div className="flex items-center gap-2">
        <Calendar className="h-4 w-4 text-muted-foreground" />
        <Select value={filters.dateRange} onValueChange={(v: DateRangePreset) => onDateRangeChange(v)}>
          <SelectTrigger className="w-[140px] h-9 bg-muted/50 border-border"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(Object.keys(DATE_RANGE_LABELS) as DateRangePreset[]).map(key => (
              <SelectItem key={key} value={key}>{DATE_RANGE_LABELS[key]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Org Scope (root only now) */}
      {(scopeOptions?.organizations?.length ?? 0) > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Org</span>
          <Select value={selectedOrgId ?? undefined} onValueChange={onOrgChange}>
            <SelectTrigger className="w-[210px] h-9 bg-muted/50 border-border"><SelectValue placeholder="Organization scope" /></SelectTrigger>
            <SelectContent>
              {scopeOptions?.organizations.map((org) => (
                <SelectItem key={org.id} value={org.id}>{org.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Trace Scope Toggle (dept_admin / super_admin) */}
      {hasTraceScopeToggle && scopeToggleOptions.length > 0 && (
        <div className="flex items-center rounded-lg border border-border bg-muted/50 p-0.5">
          {scopeToggleOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => { if (traceScope !== opt.value) onTraceScopeChange(opt.value); }}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${traceScope === opt.value ? "shadow-sm text-white" : "text-muted-foreground hover:bg-muted"}`}
              style={traceScope === opt.value ? { backgroundColor: THEME.primary } : undefined}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}

      {/* Dept Scope (super_admin in "dept" mode, or root) */}
      {(showDeptFilter || (!isSuperAdmin && !isDeptAdmin && (scopeOptions?.departments?.length ?? 0) > 0)) && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Dept</span>
          <Select value={selectedDeptId ?? undefined} onValueChange={onDeptChange}>
            <SelectTrigger className="w-[220px] h-9 bg-muted/50 border-border"><SelectValue placeholder="Select department" /></SelectTrigger>
            <SelectContent>
              {availableScopeDepartments.map((dept) => (
                <SelectItem key={dept.id} value={dept.id}>{dept.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Search */}
      <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-[400px]">
        <div className="relative flex-1">
          <Input
            icon="Search"
            placeholder="Search by trace name..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
            className="h-9 bg-muted/50 border-border"
          />
        </div>
        <Button size="sm" onClick={onSearch} className="h-9" style={{ backgroundColor: THEME.primary }}>Search</Button>
      </div>

      {/* Model Filter */}
      {availableModels.length > 0 && (
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-muted-foreground" />
          <Select
            value={filters.models.length === 1 ? filters.models[0] : filters.models.length > 1 ? "multiple" : "all"}
            onValueChange={(value) => {
              if (value === "all") onModelChange([]);
              else if (value !== "multiple") onModelChange([value]);
            }}
          >
            <SelectTrigger className="w-[180px] h-9 bg-muted/50 border-border"><SelectValue placeholder="All models" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All models</SelectItem>
              {availableModels.map(model => (
                <SelectItem key={model} value={model}>{model.split("/").pop() || model}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Clear Filters */}
      {(filters.search || filters.models.length > 0 || filters.dateRange !== "today") && (
        <Button size="sm" variant="ghost" onClick={onClearFilters} className="h-9 text-muted-foreground">
          <X className="h-4 w-4 mr-1" />Clear
        </Button>
      )}

      {((selectedOrgId && !isSuperAdmin && !isDeptAdmin) || (selectedDeptId && showDeptFilter)) && (
        <Button size="sm" variant="ghost" onClick={onClearScope} className="h-9 text-muted-foreground">
          <X className="h-4 w-4 mr-1" />Clear Scope
        </Button>
      )}

      <Button size="sm" variant="outline" onClick={onRefresh} disabled={isRefreshing || isLoading} className="h-9 ml-auto">
        <RefreshCw className={`h-4 w-4 mr-1.5 ${isRefreshing ? "animate-spin" : ""}`} />
        {isRefreshing ? "Refreshing..." : "Refresh"}
      </Button>

      {/* Fetching indicator */}
      {isFetching && (
        <div className="flex items-center gap-1.5">
          <div className="h-3.5 w-3.5 rounded-full border-2 border-t-transparent animate-spin" style={{ borderColor: THEME.primary, borderTopColor: 'transparent' }} />
          <span className="text-xs text-muted-foreground">Updating...</span>
        </div>
      )}

      {/* Active Filters Display */}
      {filters.search && (
        <Badge variant="secondary" className="gap-1">
          Search: {filters.search}
          <button onClick={() => onModelChange([])} className="ml-1 hover:opacity-70"><X className="h-3 w-3" /></button>
        </Badge>
      )}
      {selectedOrgId && !isSuperAdmin && !isDeptAdmin && (
        <Badge variant="secondary">
          Org: {(scopeOptions?.organizations ?? []).find((org) => org.id === selectedOrgId)?.name || selectedOrgId}
        </Badge>
      )}
      {selectedDeptId && showDeptFilter && (
        <Badge variant="secondary">
          Dept: {(scopeOptions?.departments ?? []).find((dept) => dept.id === selectedDeptId)?.name || selectedDeptId}
        </Badge>
      )}
      <Badge
        variant="secondary"
        className={selectedEnvironment === "production" ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400" : "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"}
      >
        Env: {selectedEnvironment === "production" ? "PROD" : "UAT"}
      </Badge>
    </div>
  );
}
