import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Calendar, Search, X, Cpu, RefreshCw } from "lucide-react";
import { THEME } from "../theme";
import { DATE_RANGE_LABELS } from "../utils";
import type {
  Filters, DateRangePreset, LangfuseEnvironment,
  ScopeOptionsResponse, DepartmentScopeOption, Metrics,
} from "../types";

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
  onDateRangeChange: (v: DateRangePreset) => void;
  onSearch: () => void;
  onModelChange: (models: string[]) => void;
  onOrgChange: (orgId: string) => void;
  onDeptChange: (deptId: string) => void;
  onClearFilters: () => void;
  onClearScope: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  isLoading: boolean;
  isFetching: boolean;
}

export function FilterBar({
  filters, searchInput, setSearchInput,
  selectedEnvironment, selectedOrgId, selectedDeptId,
  scopeOptions, availableScopeDepartments, metrics,
  onDateRangeChange, onSearch, onModelChange,
  onOrgChange, onDeptChange, onClearFilters, onClearScope,
  onRefresh, isRefreshing, isLoading, isFetching,
}: FilterBarProps) {
  const availableModels = useMemo(() => metrics?.by_model?.map(m => m.model) || [], [metrics?.by_model]);

  return (
    <div className="flex flex-wrap items-center gap-3 p-4 bg-white rounded-xl border shadow-sm">
      {/* Date Range */}
      <div className="flex items-center gap-2">
        <Calendar className="h-4 w-4" style={{ color: THEME.textSecondary }} />
        <Select value={filters.dateRange} onValueChange={(v: DateRangePreset) => onDateRangeChange(v)}>
          <SelectTrigger className="w-[140px] h-9 bg-gray-50 border-gray-200"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(Object.keys(DATE_RANGE_LABELS) as DateRangePreset[]).map(key => (
              <SelectItem key={key} value={key}>{DATE_RANGE_LABELS[key]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Org Scope */}
      {(scopeOptions?.organizations?.length ?? 0) > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide" style={{ color: THEME.textSecondary }}>Org</span>
          <Select value={selectedOrgId ?? undefined} onValueChange={onOrgChange}>
            <SelectTrigger className="w-[210px] h-9 bg-gray-50 border-gray-200"><SelectValue placeholder="Organization scope" /></SelectTrigger>
            <SelectContent>
              {scopeOptions?.organizations.map((org) => (
                <SelectItem key={org.id} value={org.id}>{org.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Dept Scope */}
      {(scopeOptions?.departments?.length ?? 0) > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide" style={{ color: THEME.textSecondary }}>Dept</span>
          <Select value={selectedDeptId ?? undefined} onValueChange={onDeptChange}>
            <SelectTrigger className="w-[220px] h-9 bg-gray-50 border-gray-200"><SelectValue placeholder="Department scope" /></SelectTrigger>
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
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: THEME.textSecondary }} />
          <Input
            placeholder="Search by trace name..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
            className="pl-9 h-9 bg-gray-50 border-gray-200"
          />
        </div>
        <Button size="sm" onClick={onSearch} className="h-9" style={{ backgroundColor: THEME.primary }}>Search</Button>
      </div>

      {/* Model Filter */}
      {availableModels.length > 0 && (
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4" style={{ color: THEME.textSecondary }} />
          <Select
            value={filters.models.length === 1 ? filters.models[0] : filters.models.length > 1 ? "multiple" : "all"}
            onValueChange={(value) => {
              if (value === "all") onModelChange([]);
              else if (value !== "multiple") onModelChange([value]);
            }}
          >
            <SelectTrigger className="w-[180px] h-9 bg-gray-50 border-gray-200"><SelectValue placeholder="All models" /></SelectTrigger>
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
        <Button size="sm" variant="ghost" onClick={onClearFilters} className="h-9" style={{ color: THEME.textSecondary }}>
          <X className="h-4 w-4 mr-1" />Clear
        </Button>
      )}

      {(selectedOrgId || selectedDeptId) && (
        <Button size="sm" variant="ghost" onClick={onClearScope} className="h-9" style={{ color: THEME.textSecondary }}>
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
          <span className="text-xs" style={{ color: THEME.textSecondary }}>Updating...</span>
        </div>
      )}

      {/* Active Filters Display */}
      {filters.search && (
        <Badge variant="secondary" className="gap-1 bg-gray-100">
          Search: {filters.search}
          <button onClick={() => onModelChange([])} className="ml-1 hover:opacity-70"><X className="h-3 w-3" /></button>
        </Badge>
      )}
      {selectedOrgId && (
        <Badge variant="secondary" className="bg-gray-100">
          Org: {(scopeOptions?.organizations ?? []).find((org) => org.id === selectedOrgId)?.name || selectedOrgId}
        </Badge>
      )}
      {selectedDeptId && (
        <Badge variant="secondary" className="bg-gray-100">
          Dept: {(scopeOptions?.departments ?? []).find((dept) => dept.id === selectedDeptId)?.name || selectedDeptId}
        </Badge>
      )}
      <Badge
        variant="secondary"
        style={selectedEnvironment === "production" ? { backgroundColor: "#dcfce7", color: "#166534" } : { backgroundColor: "#dbeafe", color: "#1e40af" }}
      >
        Env: {selectedEnvironment === "production" ? "PROD" : "UAT"}
      </Badge>
    </div>
  );
}
