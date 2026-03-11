import { useState, useMemo, useCallback, useEffect } from "react";
import useAuthStore from "@/stores/authStore";
import type { Filters, DateRangePreset, LangfuseEnvironment, ScopeOptionsResponse } from "../types";
import { getDateRangeParams, getUserTimezoneOffset } from "../utils";

export function useObservabilityFilters(scopeOptions: ScopeOptionsResponse | undefined) {
  const currentRole = useAuthStore((state) => state.role);
  const sessionRole = String(currentRole || "").toLowerCase();
  const isProvisioningAdminSessionRole = sessionRole === "root" || sessionRole === "super_admin";

  const [selectedEnvironment, setSelectedEnvironment] = useState<LangfuseEnvironment>("uat");
  const [fetchAllMode, setFetchAllMode] = useState(false);
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null);
  const [selectedDeptId, setSelectedDeptId] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>({ dateRange: "today", search: "", models: [] });
  const [searchInput, setSearchInput] = useState("");

  const normalizedRole = String(scopeOptions?.role || currentRole || "").toLowerCase();
  const roleKnown = normalizedRole.length > 0;
  const requiresFilterFirst =
    scopeOptions?.requires_filter_first ?? (normalizedRole === "root" || normalizedRole === "super_admin");
  const scopeReady = !requiresFilterFirst || Boolean(selectedOrgId || selectedDeptId);

  const availableScopeDepartments = useMemo(() => {
    const departments = scopeOptions?.departments ?? [];
    if (!selectedOrgId) return departments;
    return departments.filter((dept) => dept.org_id === selectedOrgId);
  }, [scopeOptions?.departments, selectedOrgId]);

  // Sync dept with org
  useEffect(() => {
    if (!selectedDeptId) return;
    const selectedDepartment = (scopeOptions?.departments ?? []).find((dept) => dept.id === selectedDeptId);
    if (!selectedDepartment) {
      setSelectedDeptId(null);
      return;
    }
    if (selectedOrgId && selectedDepartment.org_id !== selectedOrgId) {
      setSelectedDeptId(null);
    }
  }, [scopeOptions?.departments, selectedDeptId, selectedOrgId]);

  // Auto-set org when dept is selected
  useEffect(() => {
    if (!selectedDeptId) return;
    const selectedDepartment = (scopeOptions?.departments ?? []).find((dept) => dept.id === selectedDeptId);
    if (selectedDepartment && selectedDepartment.org_id !== selectedOrgId) {
      setSelectedOrgId(selectedDepartment.org_id);
    }
  }, [scopeOptions?.departments, selectedDeptId, selectedOrgId]);

  const dateParams = useMemo(
    () => ({
      ...getDateRangeParams(filters.dateRange),
      tz_offset: getUserTimezoneOffset(),
      ...(fetchAllMode ? { fetch_all: true as const } : {}),
    }),
    [filters.dateRange, fetchAllMode],
  );

  const scopeParams = useMemo(
    () => ({
      ...(selectedOrgId ? { org_id: selectedOrgId } : {}),
      ...(selectedDeptId ? { dept_id: selectedDeptId } : {}),
      environment: selectedEnvironment,
    }),
    [selectedOrgId, selectedDeptId, selectedEnvironment],
  );

  const handleDateRangeChange = useCallback((value: DateRangePreset) => {
    setFetchAllMode(false);
    setFilters((prev) => ({ ...prev, dateRange: value }));
  }, []);

  const handleSearch = useCallback(() => {
    setFilters((prev) => ({ ...prev, search: searchInput }));
  }, [searchInput]);

  const clearFilters = useCallback(() => {
    setFilters({ dateRange: "today", search: "", models: [] });
    setSearchInput("");
    setFetchAllMode(false);
  }, []);

  const clearScope = useCallback(() => {
    setSelectedOrgId(null);
    setSelectedDeptId(null);
    setFetchAllMode(false);
  }, []);

  const handleEnvironmentChange = useCallback((env: LangfuseEnvironment) => {
    setSelectedEnvironment(env);
    setFetchAllMode(false);
  }, []);

  const handleOrgChange = useCallback(
    (orgId: string) => {
      setFetchAllMode(false);
      setSelectedOrgId(orgId);
      if (selectedDeptId) {
        const dept = (scopeOptions?.departments ?? []).find((d) => d.id === selectedDeptId);
        if (dept && dept.org_id !== orgId) setSelectedDeptId(null);
      }
    },
    [selectedDeptId, scopeOptions?.departments],
  );

  const handleDeptChange = useCallback(
    (deptId: string) => {
      setFetchAllMode(false);
      setSelectedDeptId(deptId);
      const dept = (scopeOptions?.departments ?? []).find((d) => d.id === deptId);
      if (dept && dept.org_id !== selectedOrgId) {
        setSelectedOrgId(dept.org_id);
      }
    },
    [selectedOrgId, scopeOptions?.departments],
  );

  return {
    filters,
    setFilters,
    searchInput,
    setSearchInput,
    selectedEnvironment,
    selectedOrgId,
    selectedDeptId,
    fetchAllMode,
    setFetchAllMode,
    dateParams,
    scopeParams,
    normalizedRole,
    roleKnown,
    requiresFilterFirst,
    scopeReady,
    isProvisioningAdminSessionRole,
    availableScopeDepartments,
    handleDateRangeChange,
    handleSearch,
    handleEnvironmentChange,
    handleOrgChange,
    handleDeptChange,
    clearFilters,
    clearScope,
  };
}
