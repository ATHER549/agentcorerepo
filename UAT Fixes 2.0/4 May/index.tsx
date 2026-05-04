import { Check, ChevronDown, ChevronsUpDown, Play, Plus } from "lucide-react";
import React, { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import sampleDatasetCsvUrl from "@/data/dataset_sample/dataset_sample.csv?url";
import { AuthContext } from "@/contexts/authContext";
import type { LangfuseEnvironment } from "../ObservabilityPage/types";
import { TraceDetailDialog } from "../ObservabilityPage/components/DetailDialogs";
import { fetchTraceDetail } from "../ObservabilityPage/api";
import type { TraceDetailResponse } from "../ObservabilityPage/types";
import { api } from "@/controllers/API/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/utils/utils";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTranslation } from "react-i18next";
import useAlertStore from "@/stores/alertStore";
import { useGetRegistryModels } from "@/controllers/API/queries/models/use-get-models";
import {
  createEvaluationDataset,
  createEvaluationDatasetItem,
  createEvaluationScore,
  createEvaluator,
  DatasetExperimentJob,
  deleteEvaluationDataset,
  updateEvaluationDataset,
  deleteEvaluationDatasetItem,
  deleteEvaluationDatasetRun,
  deleteEvaluator,
  EvaluationDataset,
  EvaluationDatasetItem,
  EvaluationDatasetRun,
  EvaluationDatasetRunDetail,
  EvaluationPreset,
  EvaluationStatus,
  getAgents,
  getDatasetExperimentJob,
  getEvaluationDatasetItems,
  getEvaluationDatasetRunDetail,
  getEvaluationDatasetRuns,
  getEvaluationDatasets,
  getEvaluationPresets,
  getEvaluationScores,
  getEvaluationStatus,
  getPendingReviews,
  listEvaluators,
  runEvaluator,
  runEvaluationDatasetExperiment,
  Score,
  TraceForReview,
  uploadEvaluationDatasetItemsCsv,
  updateEvaluator,
} from "../../controllers/API/evaluation";

const FALLBACK_PRESETS: EvaluationPreset[] = [
  {
    id: "correctness",
    name: "Correctness",
    criteria:
      "Evaluate the correctness of the generation against the ground truth on a scale 0-1.",
    requires_ground_truth: true,
  },
  {
    id: "helpfulness",
    name: "Helpfulness",
    criteria:
      "Evaluate how helpful the output is in addressing the user's input on a scale 0-1.",
    requires_ground_truth: false,
  },
];

const DATASET_PROMPT_TEMPLATE = `Input:
Query: {{query}}
Generation: {{generation}}
Ground Truth: {{ground_truth}}`;

const ensureDatasetPromptTemplate = (criteria?: string | null): string => {
  const text = (criteria || "").trim();
  if (!text) return DATASET_PROMPT_TEMPLATE;
  const normalized = text.toLowerCase().replace(/\s+/g, " ");
  if (
    normalized.includes("query: {{query}}") &&
    normalized.includes("generation: {{generation}}") &&
    normalized.includes("ground truth: {{ground_truth}}")
  ) {
    return text;
  }
  return `${text}\n\n${DATASET_PROMPT_TEMPLATE}`;
};

type VisibilityOptions = {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
  role?: string;
};

export default function EvaluationPage() {
  const { t } = useTranslation();
  const { userData } = useContext(AuthContext);
  const userRole = (userData?.role || "").toLowerCase();
  const isDepartmentAdmin = userRole === "department_admin";
  const isSuperAdmin = userRole === "super_admin";
  const canMultiDept = userRole === "super_admin" || userRole === "root";
  const userId = userData?.id ?? null;
  const userDeptId = userData?.department_id ?? null;
  const isMembershipLockedRole =
    userRole === "developer" ||
    userRole === "business_user" ||
    userRole === "department_admin";
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
  });
  const [activeTab, setActiveTab] = useState("judges");
  const [selectedEnvironment, setSelectedEnvironment] = useState<LangfuseEnvironment>("uat");
  const [status, setStatus] = useState<EvaluationStatus | null>(null);
  const [recentScores, setRecentScores] = useState<Score[]>([]);
  const [pendingTraces, setPendingTraces] = useState<TraceForReview[]>([]);
  const [loading, setLoading] = useState(false);
  const [scoreFilters, setScoreFilters] = useState({ trace_id: "", name: "" });
  const [presets, setPresets] = useState<EvaluationPreset[]>([]);
  const [savedEvaluators, setSavedEvaluators] = useState<Array<any>>([]);
  const [editingEvaluator, setEditingEvaluator] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [selectedDatasetName, setSelectedDatasetName] = useState<string>("");
  const [datasetItems, setDatasetItems] = useState<EvaluationDatasetItem[]>([]);
  const [datasetRuns, setDatasetRuns] = useState<EvaluationDatasetRun[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState<boolean>(false);
  const [datasetCsvFile, setDatasetCsvFile] = useState<File | null>(null);
  const [datasetCsvUploading, setDatasetCsvUploading] = useState<boolean>(false);
  const [datasetCsvInputKey, setDatasetCsvInputKey] = useState<number>(0);
  const [datasetExperimentJob, setDatasetExperimentJob] =
    useState<DatasetExperimentJob | null>(null);
  const [isRunDetailOpen, setIsRunDetailOpen] = useState<boolean>(false);
  const [isDatasetItemsDialogOpen, setIsDatasetItemsDialogOpen] =
    useState<boolean>(false);
  const [runDetailLoading, setRunDetailLoading] = useState<boolean>(false);
  const [selectedRunDetail, setSelectedRunDetail] =
    useState<EvaluationDatasetRunDetail | null>(null);
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.name === selectedDatasetName) || null,
    [datasets, selectedDatasetName],
  );
  const [datasetForm, setDatasetForm] = useState({
    name: "",
    description: "",
    visibility: "private" as "private" | "public",
    public_scope: "" as string,
    org_id: "" as string,
    dept_id: "" as string,
    public_dept_ids: [] as string[],
  });
  const [editingDataset, setEditingDataset] = useState<EvaluationDataset | null>(null);
  const [datasetEditForm, setDatasetEditForm] = useState({
    description: "",
    visibility: "private" as string,
    public_scope: "" as string,
    org_id: "" as string,
    dept_id: "" as string,
    public_dept_ids: [] as string[],
  });
  const [datasetItemForm, setDatasetItemForm] = useState({
    input: "",
    expected_output: "",
    metadata: "",
    trace_id: "",
    source_trace_id: "",
  });
  const [datasetExperimentForm, setDatasetExperimentForm] = useState({
    experiment_name: "",
    description: "",
    agent_id: "",
    generation_model: "",
    generation_model_registry_id: "",
    evaluator_config_id: "",
    preset_id: "",
    evaluator_name: "",
    criteria: "",
    judge_model: "",
    judge_model_registry_id: "",
  });

  // Dialog States
  const [isJudgeDialogOpen, setIsJudgeDialogOpen] = useState(false);
  const [isScoreDialogOpen, setIsScoreDialogOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const fetchSeqRef = useRef(0);

  const [agentList, setAgentList] = useState<any[]>([]);
  const [judgeAgentSearch, setJudgeAgentSearch] = useState("");
  const { data: registryModels = [] } = useGetRegistryModels({ model_type: "llm", active_only: true });

  // Trace detail dialog state (for viewing trace from scores table)
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [traceDetail, setTraceDetail] = useState<TraceDetailResponse | undefined>(undefined);
  const [traceDetailLoading, setTraceDetailLoading] = useState(false);
  const [traceDetailError, setTraceDetailError] = useState(false);

  useEffect(() => {
    if (!selectedTraceId) {
      setTraceDetail(undefined);
      return;
    }
    let cancelled = false;
    setTraceDetailLoading(true);
    setTraceDetailError(false);
    fetchTraceDetail(selectedTraceId, { environment: selectedEnvironment })
      .then((data) => { if (!cancelled) setTraceDetail(data); })
      .catch(() => { if (!cancelled) setTraceDetailError(true); })
      .finally(() => { if (!cancelled) setTraceDetailLoading(false); });
    return () => { cancelled = true; };
  }, [selectedTraceId, selectedEnvironment]);

  // Per-tab fetch guards — prevent redundant refetches on every tab revisit
  const hasFetchedScoresRef = useRef(false);
  const hasFetchedDatasetsRef = useRef(false);

  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [filterSessionId, setFilterSessionId] = useState<string>("");
  const [filterTraceId, setFilterTraceId] = useState<string>("");
  const [runOnNew, setRunOnNew] = useState<boolean>(true);
  const [runOnExisting, setRunOnExisting] = useState<boolean>(true);

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setNoticeData = useAlertStore((state) => state.setNoticeData);

  // Form Data
  const [judgeForm, setJudgeForm] = useState({
    trace_id: "",
    criteria: "",
    model: "",
    name: "",
    preset_id: "",
    saved_evaluator_id: "",
    model_registry_id: "",
  });

  const filteredModels = useMemo(() => {
    if (!Array.isArray(registryModels)) return [];
    return registryModels.filter((model) => {
      if (!model) return false;
      if (
        model.id === judgeForm.model_registry_id ||
        model.id === datasetExperimentForm.generation_model_registry_id ||
        model.id === datasetExperimentForm.judge_model_registry_id
      ) {
        return true;
      }
      const showIn = (model as any).show_in;
      if (!showIn) return true;
      if (Array.isArray(showIn)) return showIn.includes("agent");
      if (typeof showIn === "string") return showIn.includes("agent");
      return true;
    });
  }, [
    registryModels,
    judgeForm.model_registry_id,
    datasetExperimentForm.generation_model_registry_id,
    datasetExperimentForm.judge_model_registry_id,
  ]);

  const toVisibilityScope = useCallback(
    (visibility?: "private" | "public", publicScope?: string) => {
      if (visibility !== "public") return "private" as const;
      return publicScope === "organization" ? ("organization" as const) : ("department" as const);
    },
    [],
  );
  const getSelectedDeptLabel = useCallback(
    (selectedIds: string[], orgId: string) => {
      if (selectedIds.length === 0) return "Select departments";
      const names = visibilityOptions.departments
        .filter((dept) => (!orgId || dept.org_id === orgId) && selectedIds.includes(dept.id))
        .map((dept) => dept.name);
      if (names.length === 0) return "Select departments";
      if (names.length <= 2) return names.join(", ");
      return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
    },
    [visibilityOptions.departments],
  );
  const getVisibilityLabel = useCallback((item: {
    visibility?: "private" | "public";
    public_scope?: "organization" | "department" | null;
  }) => {
    if (item.visibility === "private") return "Private";
    if (item.public_scope === "organization") return "Organization";
    return "Department";
  }, []);
  const getVisibilityBadgeClass = useCallback((item: {
    visibility?: "private" | "public";
    public_scope?: "organization" | "department" | null;
  }) => {
    if (item.visibility === "private") {
      return "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200";
    }
    if (item.public_scope === "organization") {
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
    }
    return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
  }, []);
  const getDepartmentScopeLabel = useCallback((item: {
    visibility?: "private" | "public";
    public_scope?: "organization" | "department" | null;
    dept_id?: string | null;
    public_dept_ids?: string[] | null;
  }) => {
    if (item.visibility === "public" && item.public_scope === "organization") {
      return "All departments";
    }
    const deptNameById = new Map(
      visibilityOptions.departments.map((dept) => [dept.id, dept.name]),
    );
    const deptIds =
      item.visibility === "public" && item.public_scope === "department"
        ? item.public_dept_ids?.length
          ? item.public_dept_ids
          : item.dept_id
            ? [item.dept_id]
            : []
        : item.dept_id
          ? [item.dept_id]
          : [];
    if (deptIds.length === 0) return "-";
    const names = deptIds.map((id) => deptNameById.get(id) || id);
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  }, [visibilityOptions.departments]);

  const getScopeDeptIds = useCallback((item: {
    dept_id?: string | null;
    public_dept_ids?: string[] | null;
  }) => {
    const ids = new Set<string>();
    (item.public_dept_ids || []).forEach((id) => ids.add(id));
    if (item.dept_id) ids.add(item.dept_id);
    return Array.from(ids);
  }, []);

  const isMultiDeptScope = useCallback((item: {
    visibility?: "private" | "public";
    public_scope?: "organization" | "department" | null;
    dept_id?: string | null;
    public_dept_ids?: string[] | null;
  }) => {
    return (
      item.visibility === "public" &&
      item.public_scope === "department" &&
      getScopeDeptIds(item).length > 1
    );
  }, [getScopeDeptIds]);

  const isDeptScopedForUser = useCallback((item: {
    dept_id?: string | null;
    public_dept_ids?: string[] | null;
  }) => {
    return Boolean(userDeptId && getScopeDeptIds(item).includes(userDeptId));
  }, [getScopeDeptIds, userDeptId]);

  const getEvaluatorOwnerId = useCallback((ev: any) => {
    return ev?.created_by_id || ev?.user_id || null;
  }, []);

  const canEditEvaluator = useCallback((ev: any) => {
    if (!userId) return false;
    return getEvaluatorOwnerId(ev) === userId;
  }, [getEvaluatorOwnerId, userId]);

  const canDeleteEvaluator = useCallback((ev: any) => {
    return canEditEvaluator(ev);
  }, [canEditEvaluator]);

  const getDatasetOwnerId = useCallback((ds: EvaluationDataset | null) => {
    return (
      ds?.created_by_id ||
      ds?.owner_user_id ||
      ds?.metadata?.app_user_id ||
      ds?.metadata?.created_by_user_id ||
      null
    );
  }, []);

  const canDeleteDataset = useCallback((ds: EvaluationDataset | null) => {
    if (!ds) return false;
    if (userRole === "root") {
      return getDatasetOwnerId(ds) === userId && !ds.org_id && !ds.dept_id;
    }
    if (userRole === "super_admin") return true;
    if (userRole === "department_admin") {
      if (isMultiDeptScope(ds)) return false;
      if (ds.visibility === "public" && ds.public_scope === "organization") return false;
      if (ds.visibility === "public" && ds.public_scope === "department") {
        return isDeptScopedForUser(ds);
      }
      if (ds.visibility === "private") return isDeptScopedForUser(ds);
      return false;
    }
    if (userRole === "developer" || userRole === "business_user") {
      return ds.visibility === "private" && getDatasetOwnerId(ds) === userId;
    }
    return false;
  }, [getDatasetOwnerId, isDeptScopedForUser, isMultiDeptScope, userId, userRole]);
  const canManageSelectedDataset = canDeleteDataset(selectedDataset);
  const datasetVisibilityScope = toVisibilityScope(datasetForm.visibility, datasetForm.public_scope);
  const datasetDepartmentsForSelectedOrg = useMemo(
    () => visibilityOptions.departments.filter((dept) => !datasetForm.org_id || dept.org_id === datasetForm.org_id),
    [visibilityOptions.departments, datasetForm.org_id],
  );
  const selectedDatasetDeptLabel = useMemo(
    () => getSelectedDeptLabel(canMultiDept ? datasetForm.public_dept_ids : datasetForm.dept_id ? [datasetForm.dept_id] : [], datasetForm.org_id),
    [canMultiDept, datasetForm.dept_id, datasetForm.org_id, datasetForm.public_dept_ids, getSelectedDeptLabel],
  );
  const setDatasetVisibilityScope = useCallback((scope: "private" | "department" | "organization") => {
    setDatasetForm((prev) => ({
      ...prev,
      visibility: scope === "private" ? "private" : "public",
      public_scope: scope === "private" ? "" : scope,
      dept_id: scope === "department" ? prev.dept_id : "",
      public_dept_ids: scope === "department" ? prev.public_dept_ids : [],
    }));
  }, []);
  const [groundTruth, setGroundTruth] = useState("");
  const [scoreForm, setScoreForm] = useState({
    trace_id: "",
    name: "",
    value: "0.5",
    comment: "",
  });
  const selectedPreset = useMemo(
    () => presets.find((preset) => preset.id === judgeForm.preset_id),
    [presets, judgeForm.preset_id],
  );
  const selectedDatasetPreset = useMemo(
    () =>
      presets.find((preset) => preset.id === datasetExperimentForm.preset_id),
    [presets, datasetExperimentForm.preset_id],
  );
  const requiresGroundTruth = Boolean(selectedPreset?.requires_ground_truth);

  const resetForms = () => {
    setJudgeForm({
      trace_id: "",
      criteria: "",
      model: "",
      name: "",
      preset_id: "",
      saved_evaluator_id: "",
      model_registry_id: "",
    });
    setGroundTruth("");
    setSelectedAgentIds([]);
    setJudgeAgentSearch("");
    setFilterSessionId("");
    setFilterTraceId("");
    setRunOnNew(true);
    setRunOnExisting(true);
    setScoreForm({ trace_id: "", name: "", value: "0.5", comment: "" });
  };

  const handleEnvironmentChange = useCallback((env: LangfuseEnvironment) => {
    setSelectedEnvironment(env);
    // Reset fetch guards so data is refetched for the new environment
    hasFetchedScoresRef.current = false;
    hasFetchedDatasetsRef.current = false;
    setRecentScores([]);
    setPendingTraces([]);
  }, []);

  const shortId = (id?: string | null) =>
    id ? `${id.substring(0, 8)}...` : "-";
  const safePendingTraces = Array.isArray(pendingTraces)
    ? pendingTraces.filter((trace) => Boolean(trace?.id))
    : [];

  const sleep = (ms: number) =>
    new Promise((resolve) => setTimeout(resolve, ms));

  const parseJsonOrString = (value: string): unknown => {
    const trimmed = value.trim();
    if (!trimmed) return undefined;
    try {
      return JSON.parse(trimmed);
    } catch {
      return trimmed;
    }
  };

  const stringifyCompact = (value: unknown): string => {
    if (value === null || value === undefined) return "-";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  };

  const fetchDatasets = async (keepSelection = true) => {
    setDatasetsLoading(true);
    try {
      const response = await getEvaluationDatasets({ limit: 100 });
      const items = Array.isArray(response?.items) ? response.items : [];
      setDatasets(items);

      if (items.length === 0) {
        setSelectedDatasetName("");
        setDatasetItems([]);
        setDatasetRuns([]);
        setIsDatasetItemsDialogOpen(false);
        return;
      }

      const hasCurrent =
        keepSelection &&
        items.some((dataset) => dataset.name === selectedDatasetName);
      if (hasCurrent && selectedDatasetName) {
        await fetchDatasetDetails(selectedDatasetName);
      } else {
        setSelectedDatasetName("");
        setDatasetItems([]);
        setDatasetRuns([]);
        setIsDatasetItemsDialogOpen(false);
      }
    } catch (error) {
      console.error("Failed to fetch datasets", error);
      setDatasets([]);
      setDatasetItems([]);
      setDatasetRuns([]);
      setIsDatasetItemsDialogOpen(false);
    } finally {
      setDatasetsLoading(false);
    }
  };

  const fetchDatasetDetails = async (datasetName: string) => {
    if (!datasetName) {
      setDatasetItems([]);
      setDatasetRuns([]);
      return;
    }

    try {
      const [itemsResult, runsResult] = await Promise.allSettled([
        getEvaluationDatasetItems(datasetName, { limit: 100 }),
        getEvaluationDatasetRuns(datasetName, { limit: 100 }),
      ]);

      if (itemsResult.status === "fulfilled") {
        setDatasetItems(
          Array.isArray(itemsResult.value?.items)
            ? itemsResult.value.items
            : [],
        );
      } else {
        setDatasetItems([]);
      }

      if (runsResult.status === "fulfilled") {
        setDatasetRuns(
          Array.isArray(runsResult.value?.items) ? runsResult.value.items : [],
        );
      } else {
        setDatasetRuns([]);
      }
    } catch (error) {
      console.error("Failed to fetch dataset details", error);
      setDatasetItems([]);
      setDatasetRuns([]);
    }
  };

  const pollDatasetJob = async (
    jobId: string,
    attempts = 30,
    delayMs = 2000,
  ) => {
    for (let i = 0; i < attempts; i += 1) {
      await sleep(delayMs);
      try {
        const job = await getDatasetExperimentJob(jobId);
        setDatasetExperimentJob(job);
        if (job.status === "completed" || job.status === "failed") {
          return job;
        }
      } catch {
        // Ignore transient failures while polling.
      }
    }
    return null;
  };

  useEffect(() => {
    // Only load data required by the default "judges" tab on mount.
    // Scores and Datasets are loaded lazily when their tabs become active.
    getEvaluationPresets()
      .then((items) => {
        if (Array.isArray(items)) {
          setPresets(items.length ? items : FALLBACK_PRESETS);
        } else {
          setPresets(FALLBACK_PRESETS);
        }
      })
      .catch(() => {
        setPresets(FALLBACK_PRESETS);
      });
    // load saved evaluators (normalize response shapes)
    listEvaluators()
      .then((items) => {
        if (Array.isArray(items)) return setSavedEvaluators(items as any);
        if (items && Array.isArray((items as any).items))
          return setSavedEvaluators((items as any).items);
        if (items && Array.isArray((items as any).data))
          return setSavedEvaluators((items as any).data);
        return setSavedEvaluators([]);
      })
      .catch(() => {
        setSavedEvaluators([]);
      });
    getAgents({ environment: selectedEnvironment })
      .then((agents) => {
        const normalized =
          agents && Array.isArray(agents.data)
            ? agents.data
            : Array.isArray(agents)
              ? agents
              : [];
        setAgentList(normalized);
      })
      .catch(() => {
        setAgentList([]);
      });
  }, [selectedEnvironment]);

  // Refresh pending traces when opening the Run Judge dialog to ensure dropdown is populated
  useEffect(() => {
    if (!isJudgeDialogOpen) return;
    let mounted = true;
    (async () => {
      try {
        const val = await getPendingReviews({ limit: 100, environment: selectedEnvironment });
        if (!mounted) return;
        if (Array.isArray(val)) {
          setPendingTraces(val);
        } else if (val && Array.isArray((val as any).items)) {
          setPendingTraces((val as any).items);
        } else if (val && Array.isArray((val as any).data)) {
          setPendingTraces((val as any).data);
        } else {
          setPendingTraces([]);
        }
      } catch (e) {
        console.error("Failed fetching pending traces:", e);
        setPendingTraces([]);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [isJudgeDialogOpen, selectedEnvironment]);

  // Load visibility options when opening the judge dialog or datasets tab
  useEffect(() => {
    if (!isJudgeDialogOpen && activeTab !== "datasets") return;
    api
      .get("/api/evaluation/visibility-options")
      .then((res) => {
        const opts = res.data || { organizations: [], departments: [] };
        setVisibilityOptions(opts);
        if (opts.organizations?.length) {
          setJudgeForm((prev) => ({ ...prev, org_id: prev.org_id || opts.organizations[0].id }));
          setDatasetForm((prev) => ({ ...prev, org_id: prev.org_id || opts.organizations[0].id }));
        }
        if (opts.departments?.length) {
          const firstDept = opts.departments[0];
          setJudgeForm((prev) => ({
            ...prev,
            dept_id: prev.dept_id || firstDept.id,
            org_id: prev.org_id || firstDept.org_id,
          }));
          setDatasetForm((prev) => ({
            ...prev,
            dept_id: prev.dept_id || firstDept.id,
            org_id: prev.org_id || firstDept.org_id,
          }));
        }
      })
      .catch(() => {});
  }, [isJudgeDialogOpen, activeTab]);

  useEffect(() => {
    if (!isMembershipLockedRole) return;
    const firstDept =
      visibilityOptions.departments.find((dept) => dept.id === userDeptId) ||
      visibilityOptions.departments[0];
    if (!firstDept) return;
    setJudgeForm((prev) => ({
      ...prev,
      org_id: firstDept.org_id,
      dept_id: prev.visibility === "public" && prev.public_scope === "organization" ? prev.dept_id : firstDept.id,
      public_dept_ids: prev.visibility === "public" && prev.public_scope === "department" ? [firstDept.id] : prev.public_dept_ids,
    }));
    setDatasetForm((prev) => ({
      ...prev,
      org_id: firstDept.org_id,
      dept_id: prev.visibility === "public" && prev.public_scope === "organization" ? prev.dept_id : firstDept.id,
      public_dept_ids: prev.visibility === "public" && prev.public_scope === "department" ? [firstDept.id] : prev.public_dept_ids,
    }));
  }, [isMembershipLockedRole, visibilityOptions.departments, userDeptId]);

  useEffect(() => {
    type VisibilityScopedForm = {
      visibility: "private" | "public";
      public_scope: string;
      org_id: string;
      dept_id: string;
      public_dept_ids: string[];
    };

    const ensureOrganizationSelection = <T extends VisibilityScopedForm>(
      form: T,
      setForm: React.Dispatch<React.SetStateAction<T>>,
    ) => {
      if (form.visibility !== "public" || form.public_scope !== "organization") return;
      const firstOrg =
        visibilityOptions.organizations[0]?.id ||
        visibilityOptions.departments[0]?.org_id ||
        "";
      if (!firstOrg || form.org_id) return;
      setForm((prev) => ({ ...prev, org_id: prev.org_id || firstOrg }));
    };

    const ensureDepartmentSelection = <T extends VisibilityScopedForm>(
      form: T,
      setForm: React.Dispatch<React.SetStateAction<T>>,
      availableDepts: { id: string; name: string; org_id: string }[],
    ) => {
      if (form.visibility !== "public" || form.public_scope !== "department") return;
      const firstDept = availableDepts[0] || visibilityOptions.departments[0];
      if (!firstDept) return;
      if (canMultiDept) {
        const hasSelectedDept = form.public_dept_ids.some((id) =>
          availableDepts.some((dept) => dept.id === id),
        );
        if (!form.org_id || !hasSelectedDept) {
          setForm((prev) => ({
            ...prev,
            org_id: prev.org_id || firstDept.org_id,
            dept_id: prev.dept_id || firstDept.id,
            public_dept_ids: hasSelectedDept ? prev.public_dept_ids : [firstDept.id],
          }));
        }
        return;
      }
      if (!form.dept_id || !form.org_id) {
        setForm((prev) => ({
          ...prev,
          org_id: prev.org_id || firstDept.org_id,
          dept_id: prev.dept_id || firstDept.id,
        }));
      }
    };

    ensureOrganizationSelection(datasetForm, setDatasetForm);
    ensureDepartmentSelection(datasetForm, setDatasetForm, datasetDepartmentsForSelectedOrg);
  }, [
    canMultiDept,
    datasetForm,
    datasetDepartmentsForSelectedOrg,
    visibilityOptions.organizations,
    visibilityOptions.departments,
  ]);

  // Lazy-load scores data only when the Scores tab becomes active or environment changes
  useEffect(() => {
    if (activeTab !== "scores") return;
    if (!hasFetchedScoresRef.current) {
      hasFetchedScoresRef.current = true;
      fetchData();
    }
  }, [activeTab, selectedEnvironment]);

  // Lazy-load dataset list and details only when the Datasets tab becomes active
  useEffect(() => {
    if (activeTab !== "datasets") return;
    if (!hasFetchedDatasetsRef.current) {
      hasFetchedDatasetsRef.current = true;
      fetchDatasets(true);
    } else if (selectedDatasetName) {
      fetchDatasetDetails(selectedDatasetName);
    }
  }, [activeTab, selectedDatasetName]);

  useEffect(() => {
    if (!datasetExperimentForm.preset_id) return;
    const preset = presets.find(
      (item) => item.id === datasetExperimentForm.preset_id,
    );
    if (!preset) return;

    const nextCriteria = ensureDatasetPromptTemplate(preset.criteria);
    setDatasetExperimentForm((prev) => {
      if (
        prev.evaluator_name === preset.name &&
        prev.criteria === nextCriteria
      ) {
        return prev;
      }
      return {
        ...prev,
        evaluator_name: preset.name,
        criteria: nextCriteria,
      };
    });
  }, [datasetExperimentForm.preset_id, presets]);

  useEffect(() => {
    if (!datasetExperimentForm.evaluator_config_id) return;
    const evaluator = savedEvaluators.find(
      (item) => item.id === datasetExperimentForm.evaluator_config_id,
    );
    if (!evaluator) return;

    const nextCriteria = ensureDatasetPromptTemplate(evaluator.criteria || "");
    const nextPresetId = evaluator.preset_id || "";
    const nextJudgeModel = evaluator.model || "";
    const nextName = evaluator.name || "";
    setDatasetExperimentForm((prev) => {
      if (
        prev.criteria === nextCriteria &&
        prev.preset_id === nextPresetId &&
        prev.judge_model === nextJudgeModel &&
        prev.evaluator_name === nextName
      ) {
        return prev;
      }
      return {
        ...prev,
        criteria: nextCriteria,
        preset_id: nextPresetId,
        judge_model: nextJudgeModel,
        evaluator_name: nextName,
      };
    });
  }, [datasetExperimentForm.evaluator_config_id, savedEvaluators]);

  const fetchData = async (
    filters: { trace_id: string; name: string } = scoreFilters,
  ) => {
    const scoreQuery: {
      limit: number;
      trace_id?: string;
      name?: string;
      environment?: string;
    } = { limit: 20, environment: selectedEnvironment };
    const traceId = filters.trace_id.trim();
    const metricName = filters.name.trim();
    if (traceId) scoreQuery.trace_id = traceId;
    if (metricName) scoreQuery.name = metricName;

    // Single fetch — no retry delays; show empty state immediately rather than
    // blocking the UI for 3+ seconds waiting for data that may not exist yet.
    const requestSeq = ++fetchSeqRef.current;
    setLoading(true);
    try {
      const [scoresResult, pendingResult, statusResult] = await Promise.allSettled([
        getEvaluationScores(scoreQuery),
        getPendingReviews({ limit: 20, environment: selectedEnvironment }),
        getEvaluationStatus(),
      ]);
      if (scoresResult.status === "fulfilled") {
        const nextScores = Array.isArray(scoresResult.value?.items)
          ? scoresResult.value.items
          : [];
        if (requestSeq !== fetchSeqRef.current) return;
        setRecentScores((prevScores) => {
          if (
            !traceId &&
            !metricName &&
            nextScores.length === 0 &&
            prevScores.length > 0
          ) {
            return prevScores;
          }
          return nextScores;
        });
      }
      if (pendingResult.status === "fulfilled") {
        if (requestSeq !== fetchSeqRef.current) return;
        const val = pendingResult.value;
        if (Array.isArray(val)) {
          setPendingTraces(val);
        } else if (val && Array.isArray((val as any).items)) {
          setPendingTraces((val as any).items);
        } else if (val && Array.isArray((val as any).data)) {
          setPendingTraces((val as any).data);
        } else {
          setPendingTraces([]);
        }
      }
      if (statusResult.status === "fulfilled") {
        if (requestSeq !== fetchSeqRef.current) return;
        setStatus(statusResult.value);
      }
    } catch (error) {
      console.error("Failed to fetch evaluation data", error);
    } finally {
      if (requestSeq === fetchSeqRef.current) {
        setLoading(false);
      }
    }
  };

  const handleRunJudge = async () => {
    // For this UI change we only support creating/running evaluators for 'new' and/or 'existing' traces
    if (!runOnNew && !runOnExisting) {
      setErrorData({
        title: "Select at least one target: New Traces or Existing Traces.",
      });
      return;
    }
    if (!judgeForm.criteria || judgeForm.criteria.trim() === "") {
      setErrorData({ title: "Provide evaluation criteria." });
      return;
    }
    if (requiresGroundTruth && !groundTruth.trim()) {
      setErrorData({
        title: "Ground truth is required for the selected preset.",
      });
      return;
    }
    if (!judgeForm.model_registry_id) {
      setErrorData({ title: "Select a judge model from the registry." });
      return;
    }
    setIsSubmitting(true);
    try {
      const targets: string[] = [];
      if (runOnExisting) targets.push("existing");
      if (runOnNew) targets.push("new");

      const payload: any = {
        name:
          judgeForm.name?.trim() || `LLM Judge - ${new Date().toISOString()}`,
        criteria: judgeForm.criteria || "",
        model_registry_id: judgeForm.model_registry_id,
        preset_id: judgeForm.preset_id || undefined,
        target: targets.length === 1 ? targets[0] : targets,
        visibility: judgeForm.visibility || "private",
      };
      if (judgeForm.visibility === "public" && judgeForm.public_scope) {
        payload.public_scope = judgeForm.public_scope;
      }
      if (judgeForm.org_id) payload.org_id = judgeForm.org_id;
      if (judgeForm.dept_id) payload.dept_id = judgeForm.dept_id;
      if (judgeForm.public_dept_ids?.length)
        payload.public_dept_ids = judgeForm.public_dept_ids;
      if (groundTruth.trim()) payload.ground_truth = groundTruth.trim();
      if (selectedAgentIds && selectedAgentIds.length)
        payload.agent_ids = selectedAgentIds;
      if (filterSessionId) payload.session_id = filterSessionId;
      if (filterTraceId) payload.trace_id = filterTraceId;

      if (editingEvaluator) {
        await updateEvaluator(editingEvaluator, payload);
        if (runOnExisting) {
          await runEvaluator(editingEvaluator, { environment: selectedEnvironment });
        }
      } else {
        await createEvaluator(payload, { environment: selectedEnvironment });
      }
      setIsJudgeDialogOpen(false);
      resetForms();
      setEditingEvaluator(null);
      // Refresh saved evaluators list
      try {
        const items = await listEvaluators();
        if (Array.isArray(items)) setSavedEvaluators(items as any);
        else if (items && Array.isArray((items as any).items))
          setSavedEvaluators((items as any).items);
        else if (items && Array.isArray((items as any).data))
          setSavedEvaluators((items as any).data);
      } catch (e) {
        // ignore
      }
      if (runOnExisting && !runOnNew) {
        setNoticeData({
          title: "Evaluator created and existing traces queued for evaluation.",
        });
      } else if (runOnNew && !runOnExisting) {
        setSuccessData({
          title: "Evaluator saved and will apply to new traces.",
        });
      } else {
        setSuccessData({ title: "Evaluator created for selected targets." });
      }
    } catch (error) {
      console.error("Failed to run judge", error);
      setErrorData({ title: "Failed to run LLM Judge" });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEditEvaluator = (id: string) => {
    const s = savedEvaluators.find((x) => x.id === id);
    if (!s) return;
    setJudgeForm({
      ...judgeForm,
      criteria: s.criteria,
      name: s.name,
      model: s.model,
      model_registry_id: s.model_registry_id || "",
      preset_id: s.preset_id || "",
      visibility: s.visibility || "private",
      public_scope: s.public_scope || "",
      org_id: s.org_id || "",
      dept_id: s.dept_id || "",
      public_dept_ids: s.public_dept_ids || [],
    });
    setGroundTruth(s.ground_truth || "");
    const target = Array.isArray(s.target) ? s.target : [];
    if (target.length === 0) {
      setRunOnExisting(true);
      setRunOnNew(false);
    } else {
      setRunOnExisting(target.includes("existing"));
      setRunOnNew(target.includes("new"));
    }
    const agentIds = Array.isArray(s.agent_ids) ? s.agent_ids : [];
    setSelectedAgentIds(agentIds);
    setFilterSessionId(s.session_id || "");
    setFilterTraceId(s.trace_id || "");
    setEditingEvaluator(id);
    setIsJudgeDialogOpen(true);
  };

  const handleDeleteEvaluator = async (id: string) => {
    try {
      await deleteEvaluator(id);
      setSavedEvaluators((s) => s.filter((it) => it.id !== id));
      setSuccessData({ title: "Evaluator deleted" });
    } catch (e) {
      setErrorData({ title: "Failed to delete evaluator" });
    }
  };

  const handleCreateScore = async () => {
    if (!scoreForm.trace_id || !scoreForm.name) return;
    setIsSubmitting(true);
    try {
      await createEvaluationScore({
        trace_id: scoreForm.trace_id,
        name: scoreForm.name,
        value: parseFloat(scoreForm.value),
        comment: scoreForm.comment,
      });
      setIsScoreDialogOpen(false);
      resetForms();
      fetchData(); // Refresh list
      setSuccessData({ title: "Score added successfully" });
    } catch (error) {
      console.error("Failed to create score", error);
      setErrorData({ title: "Failed to create score" });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCreateDataset = async () => {
    const name = datasetForm.name.trim();
    if (!name) {
      setErrorData({ title: "Dataset name is required" });
      return;
    }

    try {
      const payload: Parameters<typeof createEvaluationDataset>[0] = {
        name,
        description: datasetForm.description.trim() || undefined,
        visibility: datasetForm.visibility || "private",
      };
      if (datasetForm.visibility === "public" && datasetForm.public_scope) {
        payload.public_scope = datasetForm.public_scope;
        if (datasetForm.public_scope === "organization" && datasetForm.org_id) {
          payload.org_id = datasetForm.org_id;
        }
        if (datasetForm.public_scope === "department") {
          if (datasetForm.org_id) payload.org_id = datasetForm.org_id;
          if (datasetForm.public_dept_ids.length > 0) {
            payload.public_dept_ids = datasetForm.public_dept_ids;
          } else if (datasetForm.dept_id) {
            payload.dept_id = datasetForm.dept_id;
            payload.public_dept_ids = [datasetForm.dept_id];
          }
        }
      }
      const created = await createEvaluationDataset(payload);
      setDatasetForm({
        name: "", description: "",
        visibility: "private", public_scope: "", org_id: "", dept_id: "", public_dept_ids: [],
      });
      setSuccessData({ title: t("Dataset '{{name}}' created", { name: created.name }) });
      await fetchDatasets(false);
      setSelectedDatasetName(created.name);
    } catch (error) {
      console.error("Failed to create dataset", error);
      setErrorData({ title: "Failed to create dataset" });
    }
  };

  const handleDeleteDataset = async (datasetToDelete?: EvaluationDataset | null) => {
    const targetDataset = datasetToDelete ?? selectedDataset;
    const targetDatasetName = targetDataset?.name || selectedDatasetName;
    if (!targetDatasetName) {
      setErrorData({ title: "Select a dataset first" });
      return;
    }
    const confirmed = window.confirm(
      t(
        "Delete dataset '{{name}}'? This will remove all dataset items and experiment runs.",
        { name: targetDatasetName },
      ),
    );
    if (!confirmed) return;

    try {
      const deletedDatasetName = targetDatasetName;
      const result = await deleteEvaluationDataset(deletedDatasetName, {
        org_id: targetDataset?.org_id || undefined,
        dept_id: targetDataset?.dept_id || undefined,
      });
      if (result.status === "deleted") {
        setSuccessData({ title: t("Dataset '{{name}}' deleted", { name: deletedDatasetName }) });
      } else {
        setNoticeData({
          title: `Dataset '${deletedDatasetName}' purged${result.errors?.length ? " with some cleanup warnings" : ""}.`,
        });
      }
      setDatasets((current) =>
        current.filter((dataset) => dataset.name !== deletedDatasetName),
      );
      setSelectedDatasetName("");
      setDatasetItems([]);
      setDatasetRuns([]);
      setSelectedRunDetail(null);
      setDatasetExperimentJob(null);
      setIsDatasetItemsDialogOpen(false);
      await fetchDatasets(false);
    } catch (error) {
      console.error("Failed to delete dataset", error);
      setErrorData({ title: "Failed to delete dataset" });
    }
  };

  const handleOpenDatasetItemsDialog = async (datasetName: string) => {
    if (!datasetName) return;
    setSelectedDatasetName(datasetName);
    setIsDatasetItemsDialogOpen(true);
    if (datasetName === selectedDatasetName) {
      await fetchDatasetDetails(datasetName);
    }
  };

  const handleAddDatasetItem = async () => {
    if (!selectedDatasetName) {
      setErrorData({ title: "Select a dataset first" });
      return;
    }

    const payload: Record<string, unknown> = {};
    const parsedInput = parseJsonOrString(datasetItemForm.input);
    const parsedExpected = parseJsonOrString(datasetItemForm.expected_output);
    const parsedMetadata = parseJsonOrString(datasetItemForm.metadata);

    if (parsedInput !== undefined) payload.input = parsedInput;
    if (parsedExpected !== undefined) payload.expected_output = parsedExpected;
    if (parsedMetadata !== undefined) payload.metadata = parsedMetadata;
    if (datasetItemForm.source_trace_id.trim())
      payload.source_trace_id = datasetItemForm.source_trace_id.trim();
    if (datasetItemForm.trace_id.trim())
      payload.trace_id = datasetItemForm.trace_id.trim();

    if (Object.keys(payload).length === 0) {
      setErrorData({
        title: "Provide item input/expected output or choose a trace",
      });
      return;
    }

    try {
      await createEvaluationDatasetItem(selectedDatasetName, payload);
      setDatasetItemForm({
        input: "",
        expected_output: "",
        metadata: "",
        trace_id: "",
        source_trace_id: "",
      });
      setSuccessData({ title: "Dataset item added" });
      await fetchDatasetDetails(selectedDatasetName);
    } catch (error) {
      console.error("Failed to create dataset item", error);
      setErrorData({ title: "Failed to create dataset item" });
    }
  };

  const handleUploadDatasetCsv = async () => {
    if (!selectedDatasetName) {
      setErrorData({ title: "Select a dataset first" });
      return;
    }
    if (!datasetCsvFile) {
      setErrorData({ title: "Choose a CSV file first" });
      return;
    }

    setDatasetCsvUploading(true);
    try {
      const result = await uploadEvaluationDatasetItemsCsv(
        selectedDatasetName,
        datasetCsvFile,
      );
      await fetchDatasetDetails(selectedDatasetName);
      setDatasetCsvFile(null);
      setDatasetCsvInputKey((prev) => prev + 1);

      if (result.failed_count > 0) {
        const firstError = result.errors?.[0];
        setNoticeData({
          title: `CSV imported with partial failures: ${result.created_count} created, ${result.failed_count} failed, ${result.skipped_count} skipped.`,
          list: firstError
            ? [`Row ${firstError.row}: ${firstError.message}`]
            : undefined,
        });
      } else {
        setSuccessData({
          title: `CSV imported successfully: ${result.created_count} items created.`,
        });
      }
    } catch (error: any) {
      const detail =
        error?.response?.data?.detail || error?.message || "CSV import failed";
      console.error("Failed to import dataset CSV", error);
      setErrorData({ title: String(detail) });
    } finally {
      setDatasetCsvUploading(false);
    }
  };

  const handleDeleteDatasetItem = async (itemId: string) => {
    if (!selectedDatasetName) return;
    const confirmed = window.confirm(t("Delete dataset item '{{id}}'?", { id: itemId }));
    if (!confirmed) return;
    try {
      await deleteEvaluationDatasetItem(selectedDatasetName, itemId);
      setSuccessData({ title: "Dataset item deleted" });
      await fetchDatasetDetails(selectedDatasetName);
    } catch (error) {
      console.error("Failed to delete dataset item", error);
      setErrorData({ title: "Failed to delete dataset item" });
    }
  };

  const handleRunDatasetExperiment = async () => {
    if (!selectedDatasetName) {
      setErrorData({ title: "Select a dataset first" });
      return;
    }
    if (!datasetExperimentForm.experiment_name.trim()) {
      setErrorData({ title: "Experiment name is required" });
      return;
    }
    const hasAgent = Boolean(datasetExperimentForm.agent_id);
    const hasRegistryModel = Boolean(datasetExperimentForm.generation_model_registry_id);
    if (!hasAgent && !hasRegistryModel) {
      setErrorData({
        title:
          "Select an agent or choose a generation model from the registry.",
      });
      return;
    }

    try {
      const datasetNameAtRun = selectedDatasetName;
      const job = await runEvaluationDatasetExperiment(selectedDatasetName, {
        experiment_name: datasetExperimentForm.experiment_name.trim(),
        description: datasetExperimentForm.description.trim() || undefined,
        agent_id: datasetExperimentForm.agent_id || undefined,
        generation_model_registry_id: hasAgent
          ? undefined
          : datasetExperimentForm.generation_model_registry_id || undefined,
        evaluator_config_id:
          datasetExperimentForm.evaluator_config_id || undefined,
        preset_id: datasetExperimentForm.preset_id || undefined,
        evaluator_name:
          datasetExperimentForm.evaluator_name.trim() || undefined,
        criteria: datasetExperimentForm.criteria.trim()
          ? ensureDatasetPromptTemplate(datasetExperimentForm.criteria.trim())
          : undefined,
        judge_model_registry_id:
          datasetExperimentForm.judge_model_registry_id || undefined,
      });

      setDatasetExperimentJob({
        job_id: job.job_id,
        dataset_name: job.dataset_name,
        experiment_name: job.experiment_name,
        status: job.status,
      });
      setNoticeData({
        title: "Dataset experiment queued. Running in background.",
      });

      void pollDatasetJob(job.job_id, 900, 2000).then(async (finalJob) => {
        if (finalJob?.status === "completed") {
          setSuccessData({
            title: `Experiment "${finalJob.experiment_name}" completed`,
          });
          await fetchDatasetDetails(datasetNameAtRun);
          return;
        }
        if (finalJob?.status === "failed") {
          setErrorData({
            title: finalJob.error || "Dataset experiment failed",
          });
        }
      });
    } catch (error) {
      console.error("Failed to run dataset experiment", error);
      setErrorData({ title: "Failed to run dataset experiment" });
    }
  };

  const handleOpenRunDetail = async (run: EvaluationDatasetRun) => {
    if (!selectedDatasetName || !run?.id) return;
    setIsRunDetailOpen(true);
    setRunDetailLoading(true);
    setSelectedRunDetail(null);
    try {
      const detail = await getEvaluationDatasetRunDetail(
        selectedDatasetName,
        run.id,
        {
          item_limit: 100,
          score_limit: 50,
        },
      );
      setSelectedRunDetail(detail);
    } catch (error) {
      console.error("Failed to fetch run detail", error);
      setSelectedRunDetail(null);
      setErrorData({ title: "Failed to load run details" });
    } finally {
      setRunDetailLoading(false);
    }
  };

  const handleDeleteDatasetRun = async (run: EvaluationDatasetRun) => {
    if (!selectedDatasetName || !run?.id) return;
    const confirmed = window.confirm(t("Delete run '{{name}}'?", { name: run.name || run.id }));
    if (!confirmed) return;
    try {
      await deleteEvaluationDatasetRun(selectedDatasetName, run.id);
      setSuccessData({ title: "Run deleted" });
      if (selectedRunDetail?.run?.id === run.id) {
        setIsRunDetailOpen(false);
        setSelectedRunDetail(null);
      }
      await fetchDatasetDetails(selectedDatasetName);
    } catch (error) {
      console.error("Failed to delete run", error);
      setErrorData({ title: "Failed to delete run" });
    }
  };

  // --- Render Helpers ---

  const renderScoresList = () => {
    return (
      <div className="bg-card rounded-lg border border-border shadow-sm overflow-hidden">
        <div className="p-4 border-b border-border flex justify-between items-center bg-muted/50">
          <h3 className="font-medium">{t("Recent Scores")}</h3>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => fetchData()}>
              {t("Refresh")}
            </Button>
            <Button
              size="sm"
              onClick={() => setIsScoreDialogOpen(true)}
              className="flex items-center gap-2"
            >
              <Plus className="h-4 w-4" /> {t("Add Score")}
            </Button>
          </div>
        </div>
        <div className="p-4 border-b border-border bg-card">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Input
              placeholder={t("Filter by Trace ID")}
              value={scoreFilters.trace_id}
              onChange={(e) =>
                setScoreFilters({ ...scoreFilters, trace_id: e.target.value })
              }
            />
            <Input
              placeholder={t("Filter by Metric Name")}
              value={scoreFilters.name}
              onChange={(e) =>
                setScoreFilters({ ...scoreFilters, name: e.target.value })
              }
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={() => fetchData()} className="flex-1">
                {t("Apply Filters")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const cleared = { trace_id: "", name: "" };
                  setScoreFilters(cleared);
                  fetchData(cleared);
                }}
              >
                {t("Clear")}
              </Button>
            </div>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-foreground uppercase bg-muted">
              <tr>
                <th className="px-6 py-3">{t("Timestamp")}</th>
                <th className="px-6 py-3">{t("Trace ID")}</th>
                <th className="px-6 py-3">{t("Agent Name")}</th>
                <th className="px-6 py-3">{t("Metric")}</th>
                <th className="px-6 py-3">{t("Evaluation Score")}</th>
                <th className="px-6 py-3">{t("Source")}</th>
                <th className="px-6 py-3">{t("Comment")}</th>
              </tr>
            </thead>
            <tbody>
              {recentScores.map((score) => (
                <tr
                  key={
                    score.id ??
                    `${score.trace_id}-${score.name}-${score.created_at ?? ""}`
                  }
                  className="border-b dark:border-border hover:bg-muted/50"
                >
                  <td className="px-6 py-4">
                    {score.created_at
                      ? new Date(score.created_at).toLocaleString()
                      : "-"}
                  </td>
                  <td className="px-6 py-4 font-mono text-xs">
                    {score.trace_id ? (
                      <button
                        className="text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
                        title={`View trace: ${score.trace_id}`}
                        onClick={() => setSelectedTraceId(score.trace_id)}
                      >
                        {score.trace_id}
                      </button>
                    ) : "-"}
                  </td>
                  <td className="px-6 py-4 font-medium">
                    {score.agent_name || "-"}
                  </td>
                  <td className="px-6 py-4 font-medium">{score.name}</td>
                  <td className="px-6 py-4">
                    <span
                      className={`px-2 py-1 rounded text-xs font-semibold ${
                        score.value > 0.7
                          ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                          : score.value > 0.4
                            ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
                            : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                      }`}
                    >
                      {score.value.toFixed(2)} ({(score.value * 100).toFixed(0)}
                      %)
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="px-2 py-1 rounded text-xs bg-muted">
                      {score.source}
                    </span>
                  </td>
                  <td
                    className="px-6 py-4 text-muted-foreground truncate max-w-xs"
                    title={score.comment}
                  >
                    {score.comment || "-"}
                  </td>
                </tr>
              ))}
              {recentScores.length === 0 && (
                <tr>
                  <td
                    colSpan={7}
                    className="px-6 py-8 text-center text-muted-foreground"
                  >
                    {t("No evaluation scores found.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const [agentPopoverOpen, setAgentPopoverOpen] = useState(false);
  const [datasetJudgeModelPopoverOpen, setDatasetJudgeModelPopoverOpen] =
    useState(false);
  const [judgeModelPopoverOpen, setJudgeModelPopoverOpen] = useState(false);

  const renderDatasets = () => {
    const agentOptions = Array.from(
      new Map(
        (agentList || [])
          .map((agent: any) => {
            const id = agent?.metadata?.agent_id || agent?.id;
            if (!id) return null;
            return [
              String(id),
              {
                id: String(id),
                label:
                  agent?.metadata?.display_name || agent?.name || String(id),
              },
            ] as const;
          })
          .filter(Boolean) as Array<
          readonly [string, { id: string; label: string }]
        >,
      ).values(),
    );

    return (
      <div className="flex flex-col gap-6">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-medium">{t("Dataset Management")}</h3>
            <div className="flex items-center gap-2">
                {selectedDatasetName && canManageSelectedDataset ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleDeleteDataset}
                  >
                    {t("Delete Dataset")}
                  </Button>
                ) : null}
              <Button
                size="sm"
                variant="outline"
                onClick={() => fetchDatasets(true)}
                disabled={datasetsLoading}
              >
                {datasetsLoading ? t("Refreshing...") : t("Refresh")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setSelectedDatasetName("");
                  setDatasetItems([]);
                  setDatasetRuns([]);
                  setIsDatasetItemsDialogOpen(false);
                }}
                disabled={!selectedDatasetName}
              >
                {t("Clear Selection")}
              </Button>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Select Dataset")}</label>
              <Select
                value={selectedDatasetName || "__none__"}
                onValueChange={(value) => {
                  const nextValue = value === "__none__" ? "" : value;
                  setSelectedDatasetName(nextValue);
                  if (!nextValue) {
                    setDatasetItems([]);
                    setDatasetRuns([]);
                    setIsDatasetItemsDialogOpen(false);
                  }
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t("Choose dataset")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{t("None (unselected)")}</SelectItem>
                  {datasets.map((dataset) => (
                    <SelectItem key={dataset.id || dataset.name} value={dataset.name}>
                      {dataset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("New Dataset Name")}</label>
              <Input
                placeholder={t("e.g. support-faq-v1")}
                value={datasetForm.name}
                onChange={(e) =>
                  setDatasetForm({ ...datasetForm, name: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Description")}</label>
              <Input
                placeholder={t("Optional description")}
                value={datasetForm.description}
                onChange={(e) =>
                  setDatasetForm({
                    ...datasetForm,
                    description: e.target.value,
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Visibility Scope")}</label>
              <select
                value={datasetVisibilityScope}
                onChange={(e) =>
                  setDatasetVisibilityScope(
                    e.target.value as "private" | "department" | "organization",
                  )
                }
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="private">{t("Private")}</option>
                <option value="department">{t("Department")}</option>
                <option value="organization">{t("Organization")}</option>
              </select>
            </div>
            {datasetVisibilityScope === "organization" && (
                <div className="space-y-2">
                  <label className="text-sm font-medium">{t("Organization")}</label>
                  <select
                    value={datasetForm.org_id}
                    onChange={(e) =>
                      setDatasetForm({ ...datasetForm, org_id: e.target.value })
                    }
                    disabled={isMembershipLockedRole}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-80"
                  >
                    <option value="">{t("Select organization...")}</option>
                    {visibilityOptions.organizations.map((org) => (
                      <option key={org.id} value={org.id}>{org.name}</option>
                    ))}
                  </select>
                </div>
              )}
            {datasetVisibilityScope === "department" && (
                <>
                  {canMultiDept && (
                    <div className="space-y-2">
                      <label className="text-sm font-medium">{t("Organization")}</label>
                      <select
                        value={datasetForm.org_id}
                        onChange={(e) =>
                          setDatasetForm({ ...datasetForm, org_id: e.target.value, public_dept_ids: [] })
                        }
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      >
                        <option value="">{t("Select organization...")}</option>
                        {visibilityOptions.organizations.map((org) => (
                          <option key={org.id} value={org.id}>{org.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      {canMultiDept ? t("Departments") : t("Department")}
                    </label>
                    {canMultiDept ? (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            type="button"
                            className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm"
                          >
                            <span className="truncate text-left">{selectedDatasetDeptLabel}</span>
                            <ChevronDown className="h-4 w-4 opacity-70" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="max-h-64 w-[var(--radix-dropdown-menu-trigger-width)] overflow-y-auto">
                          {datasetDepartmentsForSelectedOrg.map((dept) => (
                            <DropdownMenuCheckboxItem
                              key={dept.id}
                              checked={datasetForm.public_dept_ids.includes(dept.id)}
                              onCheckedChange={(checked) =>
                                setDatasetForm((prev) => ({
                                  ...prev,
                                  public_dept_ids: checked
                                    ? Array.from(new Set([...prev.public_dept_ids, dept.id]))
                                    : prev.public_dept_ids.filter((id) => id !== dept.id),
                                }))
                              }
                            >
                              {dept.name}
                            </DropdownMenuCheckboxItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    ) : (
                      <select
                        value={datasetForm.dept_id}
                        disabled
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-80"
                      >
                        {visibilityOptions.departments.map((dept) => (
                          <option key={dept.id} value={dept.id}>{dept.name}</option>
                        ))}
                      </select>
                    )}
                  </div>
                </>
              )}
          </div>
          <div className="mt-4">
            <Button size="sm" onClick={handleCreateDataset}>
              <Plus className="h-4 w-4 mr-1" /> {t("Create Dataset")}
            </Button>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <h3 className="font-medium">{t("Dataset List")}</h3>
            <span className="text-xs text-muted-foreground">
              {datasets.length} dataset{datasets.length === 1 ? "" : "s"}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-foreground uppercase bg-muted">
                <tr>
                  <th className="px-4 py-3">{t("Name")}</th>
                  <th className="px-4 py-3">{t("Description")}</th>
                  <th className="px-4 py-3">{t("Visibility")}</th>
                  {isDepartmentAdmin && <th className="px-4 py-3">{t("Created By")}</th>}
                  {isSuperAdmin && <th className="px-4 py-3">{t("Department Scope")}</th>}
                  <th className="px-4 py-3">{t("Items")}</th>
                  <th className="px-4 py-3">{t("Updated")}</th>
                  <th className="px-4 py-3 text-center">{t("Actions")}</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((dataset) => {
                  const isSelected = selectedDatasetName === dataset.name;
                  const canManageDataset = canDeleteDataset(dataset);
                  return (
                    <tr
                      key={dataset.id || dataset.name}
                      className={`border-b dark:border-border hover:bg-muted/50 cursor-pointer ${
                        isSelected
                          ? "bg-slate-100 dark:bg-slate-800/70 border-l-4 border-l-slate-500"
                          : ""
                      }`}
                      onClick={() => void handleOpenDatasetItemsDialog(dataset.name)}
                    >
                      <td className="px-4 py-3">
                        <span className="font-medium">{dataset.name}</span>
                      </td>
                      <td
                        className="px-4 py-3 max-w-xl truncate"
                        title={dataset.description || ""}
                      >
                        {dataset.description || "-"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${getVisibilityBadgeClass(dataset)}`}
                        >
                          {getVisibilityLabel(dataset)}
                        </span>
                      </td>
                      {isDepartmentAdmin && (
                        <td className="px-4 py-3 max-w-[220px] truncate" title={dataset.created_by || "-"}>
                          {dataset.created_by || "-"}
                        </td>
                      )}
                      {isSuperAdmin && (
                        <td className="px-4 py-3">{getDepartmentScopeLabel(dataset)}</td>
                      )}
                      <td className="px-4 py-3">{dataset.item_count ?? "-"}</td>
                      <td className="px-4 py-3">
                        {dataset.updated_at
                          ? new Date(dataset.updated_at).toLocaleString()
                          : "-"}
                      </td>
                      <td className="px-4 py-3">
                        {canManageDataset ? (
                          <div className="flex items-center justify-center gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditingDataset(dataset);
                                setDatasetEditForm({
                                  description: dataset.description || "",
                                  visibility: dataset.visibility || "private",
                                  public_scope: dataset.public_scope || "",
                                  org_id: dataset.org_id || "",
                                  dept_id: dataset.dept_id || "",
                                  public_dept_ids: dataset.public_dept_ids || [],
                                });
                              }}
                            >
                              Edit
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleDeleteDataset(dataset);
                              }}
                            >
                              Delete
                            </Button>
                          </div>
                        ) : (
                          <div className="flex justify-center text-muted-foreground">-</div>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {datasets.length === 0 && (
                  <tr>
                    <td
                      colSpan={6 + (isDepartmentAdmin ? 1 : 0) + (isSuperAdmin ? 1 : 0)}
                      className="px-4 py-6 text-center text-muted-foreground"
                    >
                      No datasets found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <h3 className="font-medium">{t("Run Experiment")}</h3>
            <Button
              size="sm"
              variant="outline"
              onClick={() => fetchDatasetDetails(selectedDatasetName)}
              disabled={!selectedDatasetName}
            >
              Refresh Runs
            </Button>
          </div>
          <div className="p-4 border-b border-border grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Experiment Name")}</label>
              <Input
                placeholder={t("e.g. Agent v2 Regression")}
                value={datasetExperimentForm.experiment_name}
                onChange={(e) =>
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    experiment_name: e.target.value,
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Agent")}</label>
              {(() => {
                const selectedAgent = agentOptions.find(
                  (a) => a.id === datasetExperimentForm.agent_id,
                );
                const triggerLabel = datasetExperimentForm.agent_id
                  ? selectedAgent?.label ||
                    datasetExperimentForm.agent_id
                  : t("Choose agent (optional)");
                const selectAgent = (nextAgentId: string) => {
                  const next = agentOptions.find(
                    (agent) => agent.id === nextAgentId,
                  );
                  const nextExperimentName =
                    next?.label || datasetExperimentForm.experiment_name;
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    agent_id: nextAgentId,
                    experiment_name: nextAgentId
                      ? nextExperimentName
                      : datasetExperimentForm.experiment_name,
                  });
                  setAgentPopoverOpen(false);
                };
                return (
                  <Popover
                    open={agentPopoverOpen}
                    onOpenChange={setAgentPopoverOpen}
                  >
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        role="combobox"
                        aria-expanded={agentPopoverOpen}
                        className={cn(
                          "w-full justify-between font-normal",
                          !datasetExperimentForm.agent_id &&
                            "text-muted-foreground",
                        )}
                      >
                        <span className="truncate">{triggerLabel}</span>
                        <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      className="w-[var(--radix-popover-trigger-width)] p-0"
                      align="start"
                    >
                      <Command>
                        <CommandInput placeholder={t("Search agents...")} />
                        <CommandList>
                          <CommandEmpty>{t("No agents match")}</CommandEmpty>
                          <CommandItem
                            value="__none__ no agent use generation model"
                            onSelect={() => selectAgent("")}
                          >
                            <Check
                              className={cn(
                                "mr-2 h-4 w-4",
                                !datasetExperimentForm.agent_id
                                  ? "opacity-100"
                                  : "opacity-0",
                              )}
                            />
                            {t("No agent (use generation model)")}
                          </CommandItem>
                          {agentOptions.map((agent) => (
                            <CommandItem
                              key={agent.id}
                              value={agent.label}
                              onSelect={() => selectAgent(agent.id)}
                            >
                              <Check
                                className={cn(
                                  "mr-2 h-4 w-4",
                                  datasetExperimentForm.agent_id === agent.id
                                    ? "opacity-100"
                                    : "opacity-0",
                                )}
                              />
                              {agent.label}
                            </CommandItem>
                          ))}
                        </CommandList>
                      </Command>
                    </PopoverContent>
                  </Popover>
                );
              })()}
            </div>
            {!datasetExperimentForm.agent_id ? (
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  Generation Model
                </label>
                <Select
                  value={datasetExperimentForm.generation_model_registry_id || ""}
                  onValueChange={(val) => {
                    const selected = filteredModels.find((m) => m.id === val);
                    setDatasetExperimentForm({
                      ...datasetExperimentForm,
                      generation_model_registry_id: val,
                      generation_model: selected ? selected.model_name : "",
                    });
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("Select from registry")} />
                  </SelectTrigger>
                  <SelectContent>
                    {filteredModels.map((m) => (
                      <SelectItem key={m.id} value={m.id}>
                        {m.display_name} ({m.provider}/{m.model_name})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {filteredModels.length === 0 && (
                  <p className="text-xs text-amber-600">
                    {t("No models available. Add models in the Model Registry first.")}
                  </p>
                )}
              </div>
            ) : null}
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Use Saved Evaluator")}</label>
              <Select
                value={datasetExperimentForm.evaluator_config_id || "__none__"}
                onValueChange={(value) =>
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    evaluator_config_id: value === "__none__" ? "" : value,
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder={t("Optional evaluator")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{t("None")}</SelectItem>
                  {savedEvaluators.map((ev) => (
                    <SelectItem key={ev.id} value={ev.id}>
                      {ev.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {t("Evaluator Template (Preset)")}
              </label>
              <Select
                value={datasetExperimentForm.preset_id || "__none__"}
                onValueChange={(value) => {
                  if (value === "__none__") {
                    setDatasetExperimentForm({
                      ...datasetExperimentForm,
                      preset_id: "",
                      evaluator_name: "",
                    });
                    return;
                  }
                  if (value === "__custom__") {
                    setDatasetExperimentForm({
                      ...datasetExperimentForm,
                      evaluator_config_id: "",
                      preset_id: "__custom__",
                      evaluator_name: "",
                      criteria: "",
                    });
                    return;
                  }
                  const preset = presets.find((item) => item.id === value);
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    evaluator_config_id: "",
                    preset_id: value,
                    evaluator_name: preset?.name || "",
                    criteria: ensureDatasetPromptTemplate(
                      preset?.criteria || datasetExperimentForm.criteria,
                    ),
                  });
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t("Choose preset template")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{t("None")}</SelectItem>
                  {presets.map((preset) => (
                    <SelectItem key={preset.id} value={preset.id}>
                      {preset.name}
                    </SelectItem>
                  ))}
                  <SelectItem value="__custom__">{t("+ Custom Preset")}</SelectItem>
                </SelectContent>
              </Select>
              {selectedDatasetPreset?.requires_ground_truth ? (
                <p className="text-xs text-amber-600">
                  {t("This preset requires ground truth in dataset item expected outputs.")}
                </p>
              ) : null}
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Evaluator Name")}</label>
              <Input
                placeholder={t("e.g. correctness")}
                value={datasetExperimentForm.evaluator_name}
                onChange={(e) =>
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    evaluator_name: e.target.value,
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {t("Judge Model (Optional)")}
              </label>
              {(() => {
                const selectedModel = filteredModels.find(
                  (m) => m.id === datasetExperimentForm.judge_model_registry_id,
                );
                const triggerLabel = selectedModel
                  ? `${selectedModel.display_name} (${selectedModel.provider}/${selectedModel.model_name})`
                  : t("Select from registry");
                const selectModel = (id: string) => {
                  const selected = filteredModels.find((m) => m.id === id);
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    judge_model_registry_id: id,
                    judge_model: selected ? selected.model_name : "",
                  });
                  setDatasetJudgeModelPopoverOpen(false);
                };
                return (
                  <Popover
                    open={datasetJudgeModelPopoverOpen}
                    onOpenChange={setDatasetJudgeModelPopoverOpen}
                  >
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        role="combobox"
                        aria-expanded={datasetJudgeModelPopoverOpen}
                        className={cn(
                          "w-full justify-between font-normal",
                          !selectedModel && "text-muted-foreground",
                        )}
                      >
                        <span className="truncate">{triggerLabel}</span>
                        <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      className="w-[var(--radix-popover-trigger-width)] p-0"
                      align="start"
                    >
                      <Command>
                        <CommandInput placeholder={t("Search models...")} />
                        <CommandList>
                          <CommandEmpty>{t("No models match")}</CommandEmpty>
                          {filteredModels.map((m) => (
                            <CommandItem
                              key={m.id}
                              value={`${m.display_name} ${m.provider} ${m.model_name}`}
                              onSelect={() => selectModel(m.id)}
                            >
                              <Check
                                className={cn(
                                  "mr-2 h-4 w-4",
                                  datasetExperimentForm.judge_model_registry_id ===
                                    m.id
                                    ? "opacity-100"
                                    : "opacity-0",
                                )}
                              />
                              {m.display_name} ({m.provider}/{m.model_name})
                            </CommandItem>
                          ))}
                        </CommandList>
                      </Command>
                    </PopoverContent>
                  </Popover>
                );
              })()}
            </div>
            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium">
                {t("Evaluation Criteria Prompt")}
              </label>
              <textarea
                className="flex min-h-[88px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                placeholder={t("Prompt used by the evaluator")}
                value={datasetExperimentForm.criteria}
                onChange={(e) =>
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    criteria: e.target.value,
                  })
                }
              />
              <p className="text-xs text-muted-foreground">
                {t("Keep placeholders in prompt:")} <code>{"{{query}}"}</code>,{" "}
                <code>{"{{generation}}"}</code>,{" "}
                <code>{"{{ground_truth}}"}</code>.
              </p>
            </div>
            <div className="space-y-2 md:col-span-3">
              <label className="text-sm font-medium">
                {t("Description (Optional)")}
              </label>
              <Input
                placeholder={t("Experiment notes")}
                value={datasetExperimentForm.description}
                onChange={(e) =>
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    description: e.target.value,
                  })
                }
              />
            </div>
            <div className="md:col-span-3">
              <Button
                size="sm"
                onClick={handleRunDatasetExperiment}
                disabled={!selectedDatasetName}
              >
                <Play className="h-4 w-4 mr-1" /> {t("Run Experiment")}
              </Button>
            </div>
          </div>
          {datasetExperimentJob && (
            <div className="p-4 border-b border-border text-sm">
              <span className="font-medium">{t("Latest Job:")}</span>{" "}
              <span className="font-mono">{datasetExperimentJob.job_id}</span>{" "}
              <span className="ml-2">
                {t("Status")}: {datasetExperimentJob.status}
              </span>
              {datasetExperimentJob.status === "queued" ||
              datasetExperimentJob.status === "running" ? (
                <div className="mt-3">
                  <div className="h-2 w-full rounded bg-muted overflow-hidden">
                    <div className="h-full w-1/3 bg-[#da2128] animate-pulse" />
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {t('Experiment "{{name}}" is running in background.', {
                      name: datasetExperimentJob.experiment_name,
                    })}
                  </div>
                </div>
              ) : null}
              {datasetExperimentJob.status === "completed" ? (
                <div className="mt-2 text-xs text-green-700 dark:text-green-400">
                  {t('Experiment "{{name}}" completed.', {
                    name: datasetExperimentJob.experiment_name,
                  })}
                </div>
              ) : null}
              {datasetExperimentJob.error ? (
                <span className="ml-2 text-red-600">
                  {datasetExperimentJob.error}
                </span>
              ) : null}
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-foreground uppercase bg-muted">
                <tr>
                  <th className="px-4 py-3">{t("Timestamp")}</th>
                  <th className="px-4 py-3">{t("Run ID")}</th>
                  <th className="px-4 py-3">{t("Run Name")}</th>
                  <th className="px-4 py-3">{t("Description")}</th>
                  <th className="px-4 py-3">{t("Action")}</th>
                </tr>
              </thead>
              <tbody>
                {datasetRuns.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b dark:border-border hover:bg-muted/50 cursor-pointer"
                    onClick={() => handleOpenRunDetail(run)}
                  >
                    <td className="px-4 py-3">
                      {run.created_at
                        ? new Date(run.created_at).toLocaleString()
                        : "-"}
                    </td>
                    <td
                      className="px-4 py-3 font-mono text-xs text-blue-600 dark:text-blue-400"
                      title={t("Click to view run details")}
                    >
                      {run.id}
                    </td>
                    <td className="px-4 py-3">{run.name}</td>
                    <td
                      className="px-4 py-3 max-w-xl truncate"
                      title={run.description || ""}
                    >
                      {run.description || "-"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenRunDetail(run);
                          }}
                        >
                          {t("View")}
                        </Button>
                          {canManageSelectedDataset && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteDatasetRun(run);
                              }}
                            >
                              {t("Delete")}
                            </Button>
                          )}
                      </div>
                    </td>
                  </tr>
                ))}
                {datasetRuns.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-4 py-6 text-center text-muted-foreground"
                    >
                      {t("No experiment runs found.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background">
      <div className="flex flex-none items-center justify-between border-b px-6 py-4">
        <div className="flex flex-col gap-1">
          <h2 className="text-2xl font-semibold tracking-tight">{t("Evaluation")}</h2>
          <p className="text-sm text-muted-foreground">
            {t("Monitor quality metrics, run LLM judges, and review traces.")}
          </p>
        </div>
        {/* Environment Toggle */}
        <div className="flex items-center rounded-lg border bg-muted/50 p-1">
          {([
            { value: "uat" as const, label: "UAT" },
            { value: "production" as const, label: "PROD" },
          ]).map((env) => (
            <button
              key={env.value}
              onClick={() => { if (selectedEnvironment !== env.value) handleEnvironmentChange(env.value); }}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${selectedEnvironment === env.value ? "shadow-sm text-white" : "text-muted-foreground hover:bg-muted"}`}
              style={selectedEnvironment === env.value ? { backgroundColor: "#da2128" } : undefined}
            >
              {env.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-hidden p-6">
        <div className="flex flex-col h-full w-full max-w-[1600px] mx-auto">
          {/* Tabs Header */}
          <div className="flex border-b border-border mb-6">
            <button
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "judges"
                  ? "border-[#da2128] text-[#da2128]"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setActiveTab("judges")}
            >
              {t("LLM Judges")}
            </button>
            <button
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "datasets"
                  ? "border-[#da2128] text-[#da2128]"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setActiveTab("datasets")}
            >
              {t("Datasets")}
            </button>
            <button
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "scores"
                  ? "border-[#da2128] text-[#da2128]"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setActiveTab("scores")}
            >
              {t("Scores")}
            </button>
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-auto">
            <>
              {activeTab === "scores" && (
                loading ? (
                  <div className="flex flex-col items-center justify-center h-64 gap-3">
                    <div
                      className="animate-spin rounded-full h-8 w-8 border-2 border-border"
                      style={{ borderTopColor: "#da2128" }}
                    />
                    <p className="text-sm text-muted-foreground">{t("Loading scores...")}</p>
                  </div>
                ) : renderScoresList()
              )}
              {activeTab === "judges" && (
                  <div className="flex flex-col gap-6">
                    <div className="p-8 text-center bg-card rounded-lg border border-border">
                      <h3 className="text-lg font-medium mb-2">
                        {t("LLM Judges Configuration")}
                      </h3>
                      <p className="text-muted-foreground mb-6">
                        {t("Configure automated evaluators to grade your traces based on custom criteria.")}
                      </p>
                      {status && !status.langfuse_available && (
                        <p className="text-sm text-red-600 dark:text-red-400 mb-4">
                          {t("Langfuse is not configured. Please set LANGFUSE_* environment variables.")}
                        </p>
                      )}
                      {status && !status.llm_judge_available && (
                        <p className="text-sm text-amber-600 dark:text-amber-400 mb-4">
                          {t("LLM Judge is unavailable. Please install LiteLLM in the backend.")}
                        </p>
                      )}
                      <button
                        onClick={() => {
                          setEditingEvaluator(null);
                          resetForms();
                          setIsJudgeDialogOpen(true);
                        }}
                        className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 transition-colors flex items-center gap-2 mx-auto"
                      >
                        <Play className="h-4 w-4" />
                        {t("Create New Judge")}
                      </button>
                    </div>

                    {/* Saved Evaluators List */}
                    <div className="bg-card rounded-lg border border-border shadow-sm overflow-hidden">
                      <div className="p-4 border-b border-border flex justify-between items-center bg-muted/50">
                        <h3 className="font-medium">{t("Saved Evaluators")}</h3>
                        <div className="flex items-center gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={async () => {
                              try {
                                const items = await listEvaluators();
                                if (Array.isArray(items))
                                  setSavedEvaluators(items as any);
                                else if (
                                  items &&
                                  Array.isArray((items as any).items)
                                )
                                  setSavedEvaluators((items as any).items);
                                else if (
                                  items &&
                                  Array.isArray((items as any).data)
                                )
                                  setSavedEvaluators((items as any).data);
                              } catch {}
                            }}
                          >
                            {t("Refresh")}
                          </Button>
                        </div>
                      </div>
                      <div className="overflow-x-auto p-4">
                        {savedEvaluators.length === 0 ? (
                          <div className="text-sm text-muted-foreground">
                            {t("No saved evaluators.")}
                          </div>
                        ) : (
                          <table className="w-full text-sm text-left">
                            <thead className="text-xs text-foreground uppercase bg-muted">
                              <tr>
                                <th className="px-4 py-2">{t("Name")}</th>
                                <th className="px-4 py-2">{t("Preset")}</th>
                                <th className="px-4 py-2">{t("Model")}</th>
                                <th className="px-4 py-2">{t("Agents")}</th>
                                <th className="px-4 py-2">{t("Action")}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {savedEvaluators.map((ev) => {
                                const presetName = !ev.preset_id || ev.preset_id === "__custom__" 
                                  ? t("Custom") 
                                  : (presets.find(p => p.id === ev.preset_id)?.name || ev.preset_id);
                                
                                const agentIds = Array.isArray(ev.agent_ids) ? ev.agent_ids : [];
                                const agentLabels = agentIds.length > 0 ? agentIds.map(id => {
                                  const f = agentList.find((a: any) => (a.metadata?.agent_id || a.id || a.metadata?.endpoint_name || "") === id);
                                  if (f) return f.metadata?.display_name || f.name || f.metadata?.endpoint_name || f.id || id;
                                  return id;
                                }).join(", ") : "—";

                                return (
                                <tr
                                  key={ev.id}
                                  className="border-b dark:border-border hover:bg-muted/50"
                                >
                                  <td className="px-4 py-3 font-medium">
                                    {ev.name}
                                  </td>
                                  <td className="px-4 py-3">{presetName}</td>
                                  <td className="px-4 py-3">{ev.model}</td>
                                  <td className="px-4 py-3 truncate max-w-[200px]" title={agentLabels}>
                                    {agentLabels}
                                  </td>
                                    <td className="px-4 py-3">
                                      <div className="flex items-center gap-2">
                                        {canEditEvaluator(ev) && (
                                          <Button
                                            size="sm"
                                            onClick={() =>
                                              handleEditEvaluator(ev.id)
                                            }
                                          >
                                            Edit
                                          </Button>
                                        )}
                                        {canDeleteEvaluator(ev) && (
                                          <Button
                                            size="sm"
                                            variant="ghost"
                                            onClick={async () => {
                                              try {
                                                await handleDeleteEvaluator(ev.id);
                                              } catch {}
                                            }}
                                          >
                                            Delete
                                          </Button>
                                        )}
                                      </div>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        )}
                      </div>
                    </div>

                  </div>
                )}
                {activeTab === "datasets" && renderDatasets()}
            </>
          </div>
        </div>
      </div>

      {/* Run Judge Dialog */}
      <Dialog open={isJudgeDialogOpen} onOpenChange={(open) => { setIsJudgeDialogOpen(open); if (!open) resetForms(); }}>
        <DialogContent className="max-w-2xl w-full max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("Run LLM Judge")}</DialogTitle>
            <DialogDescription>
              {t("Evaluate a specific trace using an LLM based on your criteria.")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                {t("Choose where the evaluator should run.")}
              </p>
            </div>
            <div className="space-y-2">
              <label className="flex items-center gap-2">
                <Checkbox
                  checked={runOnNew}
                  onCheckedChange={(checked) => setRunOnNew(checked === true)}
                />
                <span className="text-sm">{t("Run on New Traces")}</span>
              </label>
              <label className="flex items-center gap-2">
                <Checkbox
                  checked={runOnExisting}
                  onCheckedChange={(checked) =>
                    setRunOnExisting(checked === true)
                  }
                />
                <span className="text-sm">{t("Run on Existing Traces")}</span>
              </label>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-2">
                <label className="text-sm font-medium">{t("Use a Preset")}</label>
                <Select
                  value={judgeForm.preset_id}
                  onValueChange={(val) => {
                    if (val === "__custom__") {
                      setJudgeForm({
                        ...judgeForm,
                        criteria: "",
                        name: "",
                        preset_id: "__custom__",
                        saved_evaluator_id: "",
                      });
                      return;
                    }
                    const p = presets.find((x) => x.id === val);
                    if (p)
                      setJudgeForm({
                        ...judgeForm,
                        criteria: p.criteria,
                        name: p.name,
                        preset_id: val,
                        saved_evaluator_id: "",
                      });
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("Choose a preset")} />
                  </SelectTrigger>
                  <SelectContent>
                    {presets.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                      </SelectItem>
                    ))}
                    <SelectItem value="__custom__">{t("+ Custom Preset")}</SelectItem>
                  </SelectContent>
                </Select>
                {selectedPreset?.requires_ground_truth && (
                  <p className="text-xs text-amber-600">
                    {t("This preset requires ground truth.")}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">{t("Agents")}</label>
                <Input
                  placeholder={t("Search agents...")}
                  value={judgeAgentSearch}
                  onChange={(e) => setJudgeAgentSearch(e.target.value)}
                  className="mb-2"
                />
                <div className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm max-h-44 overflow-y-auto">
                  {(() => {
                    if (!agentList || agentList.length === 0) {
                      return (
                        <div className="text-sm text-muted-foreground py-2">
                          {t("No agents available")}
                        </div>
                      );
                    }
                    const query = judgeAgentSearch.trim().toLowerCase();
                    const rows = agentList
                      .map((f: any) => {
                        const fid =
                          f.metadata?.agent_id ||
                          f.id ||
                          f.metadata?.endpoint_name ||
                          "";
                        if (!fid) return null;
                        const label =
                          f.metadata?.display_name ||
                          f.name ||
                          f.metadata?.endpoint_name ||
                          f.id ||
                          fid;
                        return { fid, label: String(label) };
                      })
                      .filter(
                        (
                          r,
                        ): r is { fid: string; label: string } => r !== null,
                      )
                      .filter((r) =>
                        query ? r.label.toLowerCase().includes(query) : true,
                      );
                    if (rows.length === 0) {
                      return (
                        <div className="text-sm text-muted-foreground py-2">
                          {t('No agents match "{{query}}"', {
                            query: judgeAgentSearch,
                          })}
                        </div>
                      );
                    }
                    return rows.map(({ fid, label }) => {
                      const checked = selectedAgentIds.includes(fid);
                      return (
                        <label
                          key={fid}
                          className="flex items-center gap-2 py-1"
                        >
                          <Checkbox
                            checked={checked}
                            onCheckedChange={(next) => {
                              const isChecked = next === true;
                              if (isChecked) {
                                setSelectedAgentIds((s) =>
                                  Array.from(new Set([...s, fid])),
                                );
                              } else {
                                setSelectedAgentIds((s) =>
                                  s.filter((x) => x !== fid),
                                );
                              }
                            }}
                          />
                          <span className="text-sm">{label}</span>
                        </label>
                      );
                    });
                  })()}
                </div>
                <p className="text-xs text-muted-foreground">
                  {t("Select one or more agents (agents) to target.")}
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Judge Model")}</label>
              {(() => {
                const selectedModel = filteredModels.find(
                  (m) => m.id === judgeForm.model_registry_id,
                );
                const triggerLabel = selectedModel
                  ? `${selectedModel.display_name} (${selectedModel.provider}/${selectedModel.model_name})`
                  : t("Select a model from registry");
                const selectModel = (id: string) => {
                  const selected = filteredModels.find((m) => m.id === id);
                  setJudgeForm({
                    ...judgeForm,
                    model_registry_id: id,
                    model: selected ? selected.model_name : judgeForm.model,
                  });
                  setJudgeModelPopoverOpen(false);
                };
                return (
                  <Popover
                    open={judgeModelPopoverOpen}
                    onOpenChange={setJudgeModelPopoverOpen}
                  >
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        role="combobox"
                        aria-expanded={judgeModelPopoverOpen}
                        className={cn(
                          "w-full justify-between font-normal",
                          !selectedModel && "text-muted-foreground",
                        )}
                      >
                        <span className="truncate">{triggerLabel}</span>
                        <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      className="w-[var(--radix-popover-trigger-width)] p-0"
                      align="start"
                    >
                      <Command>
                        <CommandInput placeholder={t("Search models...")} />
                        <CommandList>
                          <CommandEmpty>{t("No models match")}</CommandEmpty>
                          {filteredModels.map((m) => (
                            <CommandItem
                              key={m.id}
                              value={`${m.display_name} ${m.provider} ${m.model_name}`}
                              onSelect={() => selectModel(m.id)}
                            >
                              <Check
                                className={cn(
                                  "mr-2 h-4 w-4",
                                  judgeForm.model_registry_id === m.id
                                    ? "opacity-100"
                                    : "opacity-0",
                                )}
                              />
                              {m.display_name} ({m.provider}/{m.model_name})
                            </CommandItem>
                          ))}
                        </CommandList>
                      </Command>
                    </PopoverContent>
                  </Popover>
                );
              })()}
              {filteredModels.length === 0 && (
                <p className="text-xs text-amber-600">
                  {t("No models available. Add models in the Model Registry first.")}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {t("Model and API key are resolved from the registry.")}
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Evaluator Name")}</label>
              <Input
                placeholder={t("e.g. My Custom Evaluator")}
                value={judgeForm.name}
                onChange={(e) =>
                  setJudgeForm({ ...judgeForm, name: e.target.value })
                }
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Evaluation Criteria")}</label>
              <textarea
                className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder={t("e.g. Is the answer helpful and accurate?")}
                value={judgeForm.criteria}
                onChange={(e) =>
                  setJudgeForm({ ...judgeForm, criteria: e.target.value })
                }
              />
            </div>

            {(requiresGroundTruth || judgeForm.preset_id === "__custom__") && (
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  {t("Ground Truth")}
                  {!requiresGroundTruth && <span className="text-muted-foreground font-normal ml-1">({t("Optional")})</span>}
                </label>
                <textarea
                  className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  placeholder={t("Provide expected answer/output used as reference for evaluation.")}
                  value={groundTruth}
                  onChange={(e) => setGroundTruth(e.target.value)}
                />
              </div>
            )}

          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setEditingEvaluator(null);
                setIsJudgeDialogOpen(false);
              }}
            >
              {t("Cancel")}
            </Button>
            <Button onClick={handleRunJudge} disabled={isSubmitting}>
              {isSubmitting ? t("Starting...") : t("Run Evaluation")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dataset Items Dialog */}
      <Dialog
        open={isDatasetItemsDialogOpen}
        onOpenChange={(open) => {
          setIsDatasetItemsDialogOpen(open);
          if (!open) {
            setDatasetCsvFile(null);
            setDatasetCsvInputKey((prev) => prev + 1);
          }
        }}
      >
        <DialogContent className="w-[96vw] max-w-6xl max-h-[90vh] overflow-hidden flex flex-col p-0">
          <DialogHeader className="px-6 pt-6">
            <DialogTitle>{t("Dataset Items")}</DialogTitle>
            <DialogDescription>
              {selectedDatasetName
                ? t("Manage dataset items for '{{name}}'.", { name: selectedDatasetName })
                : t("Select a dataset to view items.")}
            </DialogDescription>
          </DialogHeader>
          {selectedDatasetName ? (
            <div className="flex-1 overflow-y-auto px-6 pb-4 space-y-4 py-2">
              <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                <div className="space-y-1">
                  <label className="text-sm font-medium">{t("Import CSV")}</label>
                  {canManageSelectedDataset ? (
                    <>
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          key={datasetCsvInputKey}
                          type="file"
                          accept=".csv,text/csv"
                          onChange={(e) =>
                            setDatasetCsvFile(e.target.files?.[0] || null)
                          }
                          className="block w-full max-w-md text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-card file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-muted/50"
                        />
                        <Button
                          size="sm"
                          onClick={handleUploadDatasetCsv}
                          disabled={!datasetCsvFile || datasetCsvUploading}
                        >
                          {datasetCsvUploading ? t("Uploading...") : t("Upload CSV")}
                        </Button>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {t("Supported headers:")} <code>input</code>,{" "}
                        <code>expected_output</code>, <code>metadata</code>,{" "}
                        <code>trace_id</code>, <code>source_trace_id</code>.{" "}
                        <a
                          href={sampleDatasetCsvUrl}
                          download="dataset_sample.csv"
                          className="text-primary underline hover:no-underline"
                        >
                          {t("Download sample CSV")}
                        </a>
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      {t("CSV import is available only to users who can manage this dataset.")}
                    </p>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => fetchDatasetDetails(selectedDatasetName)}
                >
                  {t("Refresh Items")}
                </Button>
              </div>
              <div className="border rounded">
                <div className="p-4 border-b border-border grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("Input")}</label>
                    <textarea
                      className="flex min-h-[88px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      placeholder={t('Text or JSON, e.g. {"question":"What is VAT?"}')}
                      value={datasetItemForm.input}
                      onChange={(e) =>
                        setDatasetItemForm({
                          ...datasetItemForm,
                          input: e.target.value,
                        })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      {t("Expected Output")}
                    </label>
                    <textarea
                      className="flex min-h-[88px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      placeholder={t("Optional expected output (text or JSON)")}
                      value={datasetItemForm.expected_output}
                      onChange={(e) =>
                        setDatasetItemForm({
                          ...datasetItemForm,
                          expected_output: e.target.value,
                        })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      {t("Metadata (Optional)")}
                    </label>
                    <textarea
                      className="flex min-h-[88px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      placeholder={t('JSON object, e.g. {"tag":"prod-trace","lang":"en"}')}
                      value={datasetItemForm.metadata}
                      onChange={(e) =>
                        setDatasetItemForm({
                          ...datasetItemForm,
                          metadata: e.target.value,
                        })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      {t("Add From Existing Trace")}
                    </label>
                    <Select
                      value={datasetItemForm.trace_id || "__none__"}
                      onValueChange={(value) =>
                        setDatasetItemForm({
                          ...datasetItemForm,
                          trace_id: value === "__none__" ? "" : value,
                        })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder={t("Pick a trace (optional)")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__">{t("None")}</SelectItem>
                        {safePendingTraces.map((trace) => (
                          <SelectItem key={trace.id} value={trace.id}>
                            {trace.name || trace.id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      {t("Source Trace ID (Optional)")}
                    </label>
                    <Input
                      placeholder={t("Trace ID reference")}
                      value={datasetItemForm.source_trace_id}
                      onChange={(e) =>
                        setDatasetItemForm({
                          ...datasetItemForm,
                          source_trace_id: e.target.value,
                        })
                      }
                    />
                  </div>
                  <div className="md:col-span-2">
                    {canManageSelectedDataset ? (
                      <Button size="sm" onClick={handleAddDatasetItem}>
                        <Plus className="h-4 w-4 mr-1" /> Add Dataset Item
                      </Button>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        {t("Item creation is available only to users who can manage this dataset.")}
                      </p>
                    )}
                  </div>
                </div>
                <div className="max-h-[420px] overflow-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs text-foreground uppercase bg-muted">
                      <tr>
                        <th className="px-4 py-3">{t("Timestamp")}</th>
                        <th className="px-4 py-3">{t("Item ID")}</th>
                        <th className="px-4 py-3">{t("Trace ID")}</th>
                        <th className="px-4 py-3">{t("Input")}</th>
                        <th className="px-4 py-3">{t("Expected Output")}</th>
                        <th className="px-4 py-3">{t("Metadata")}</th>
                        <th className="px-4 py-3">{t("Status")}</th>
                        <th className="px-4 py-3">{t("Action")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {datasetItems.map((item) => (
                        <tr
                          key={item.id}
                          className="border-b dark:border-border hover:bg-muted/50"
                        >
                          <td className="px-4 py-3">
                            {item.created_at
                              ? new Date(item.created_at).toLocaleString()
                              : "-"}
                          </td>
                          <td className="px-4 py-3 font-mono text-xs">
                            {item.id}
                          </td>
                          <td className="px-4 py-3 font-mono text-xs">
                            {item.source_trace_id || "-"}
                          </td>
                          <td
                            className="px-4 py-3 max-w-xs truncate"
                            title={stringifyCompact(item.input)}
                          >
                            {stringifyCompact(item.input)}
                          </td>
                          <td
                            className="px-4 py-3 max-w-xs truncate"
                            title={stringifyCompact(item.expected_output)}
                          >
                            {stringifyCompact(item.expected_output)}
                          </td>
                          <td
                            className="px-4 py-3 max-w-xs truncate"
                            title={stringifyCompact(item.metadata)}
                          >
                            {stringifyCompact(item.metadata)}
                          </td>
                          <td className="px-4 py-3">{item.status || "-"}</td>
                            <td className="px-4 py-3">
                              {canManageSelectedDataset && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => handleDeleteDatasetItem(item.id)}
                                >
                                  Delete
                                </Button>
                              )}
                            </td>
                        </tr>
                      ))}
                      {datasetItems.length === 0 && (
                        <tr>
                          <td
                            colSpan={8}
                            className="px-4 py-6 text-center text-muted-foreground"
                          >
                            No dataset items found.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto px-6 py-8 text-center text-sm text-muted-foreground">
              Select a dataset from the dataset list.
            </div>
          )}
          <DialogFooter className="px-6 pb-6 pt-3 border-t border-border">
            <Button
              variant="outline"
              onClick={() => setIsDatasetItemsDialogOpen(false)}
            >
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dataset Run Detail Dialog */}
      <Dialog
        open={isRunDetailOpen}
        onOpenChange={(open) => {
          setIsRunDetailOpen(open);
          if (!open) {
            setSelectedRunDetail(null);
          }
        }}
      >
        <DialogContent className="max-w-5xl w-full">
          <DialogHeader>
            <DialogTitle>{t("Dataset Run Details")}</DialogTitle>
            <DialogDescription>
              {t("Inspect traces and scores generated for this experiment run.")}
            </DialogDescription>
          </DialogHeader>
          {runDetailLoading ? (
            <div className="flex flex-col items-center justify-center py-10 gap-3">
              <div
                className="animate-spin rounded-full h-8 w-8 border-2 border-border"
                style={{ borderTopColor: "#da2128" }}
              />
              <p className="text-sm text-muted-foreground">{t("Loading run details...")}</p>
            </div>
          ) : selectedRunDetail ? (
            <div className="space-y-4 py-2">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                <div className="rounded border p-3">
                  <div className="text-xs text-muted-foreground">{t("Run ID")}</div>
                  <div className="font-mono break-all">
                    {selectedRunDetail.run.id}
                  </div>
                </div>
                <div className="rounded border p-3">
                  <div className="text-xs text-muted-foreground">{t("Run Name")}</div>
                  <div>{selectedRunDetail.run.name}</div>
                </div>
                <div className="rounded border p-3">
                  <div className="text-xs text-muted-foreground">{t("Items")}</div>
                  <div>{selectedRunDetail.item_count}</div>
                </div>
              </div>

              <div className="max-h-[420px] overflow-auto border rounded">
                <table className="w-full text-sm text-left">
                  <thead className="text-xs text-foreground uppercase bg-muted">
                    <tr>
                      <th className="px-4 py-3">{t("Run Item ID")}</th>
                      <th className="px-4 py-3">{t("Trace ID")}</th>
                      <th className="px-4 py-3">{t("Trace Name")}</th>
                      <th className="px-4 py-3">{t("Input")}</th>
                      <th className="px-4 py-3">{t("Output")}</th>
                      <th className="px-4 py-3">{t("Scores")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRunDetail.items.map((item) => (
                      <tr
                        key={item.id}
                        className="border-b dark:border-border align-top"
                      >
                        <td className="px-4 py-3 font-mono text-xs">
                          {item.id}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">
                          {item.trace_id || "-"}
                        </td>
                        <td className="px-4 py-3">{item.trace_name || "-"}</td>
                        <td
                          className="px-4 py-3 max-w-[260px] truncate"
                          title={stringifyCompact(item.trace_input)}
                        >
                          {stringifyCompact(item.trace_input)}
                        </td>
                        <td
                          className="px-4 py-3 max-w-[260px] truncate"
                          title={stringifyCompact(item.trace_output)}
                        >
                          {stringifyCompact(item.trace_output)}
                        </td>
                        <td className="px-4 py-3">
                          {item.score_count > 0 ? (
                            <div className="space-y-1">
                              {item.scores.slice(0, 4).map((score) => (
                                <div
                                  key={
                                    score.id ||
                                    `${score.name}-${score.created_at || ""}`
                                  }
                                  className="text-xs"
                                >
                                  <span className="font-medium">
                                    {score.name}
                                  </span>
                                  : {score.value.toFixed(2)}
                                </div>
                              ))}
                              {item.scores.length > 4 ? (
                                <div className="text-xs text-muted-foreground">
                                  {t("+{{count}} more", { count: item.scores.length - 4 })}
                                </div>
                              ) : null}
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              {t("No scores")}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {selectedRunDetail.items.length === 0 && (
                      <tr>
                        <td
                          colSpan={6}
                          className="px-4 py-6 text-center text-muted-foreground"
                        >
                          {t("No run items found.")}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="py-8 text-center text-sm text-muted-foreground">
              {t("No run details available.")}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsRunDetailOpen(false)}>
              {t("Close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create Score Dialog */}
      <Dialog open={isScoreDialogOpen} onOpenChange={(open) => { setIsScoreDialogOpen(open); if (!open) resetForms(); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("Add Manual Score")}</DialogTitle>
            <DialogDescription>{t("Manually evaluate a trace.")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Trace ID")}</label>
              <Input
                placeholder={t("Trace ID")}
                value={scoreForm.trace_id}
                onChange={(e) =>
                  setScoreForm({ ...scoreForm, trace_id: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Metric Name")}</label>
              <Input
                placeholder={t("e.g. Accuracy, User Satisfaction")}
                value={scoreForm.name}
                onChange={(e) =>
                  setScoreForm({ ...scoreForm, name: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Score (0.0 - 1.0)")}</label>
              <Input
                type="number"
                min="0"
                max="1"
                step="0.1"
                value={scoreForm.value}
                onChange={(e) =>
                  setScoreForm({ ...scoreForm, value: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Comment (Optional)")}</label>
              <Input
                placeholder={t("Reasoning...")}
                value={scoreForm.comment}
                onChange={(e) =>
                  setScoreForm({ ...scoreForm, comment: e.target.value })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsScoreDialogOpen(false)}
            >
              {t("Cancel")}
            </Button>
            <Button onClick={handleCreateScore} disabled={isSubmitting}>
              {isSubmitting ? t("Saving...") : t("Save Score")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dataset Dialog — same visibility pattern as LLM Judge */}
      <Dialog open={!!editingDataset} onOpenChange={(open) => { if (!open) setEditingDataset(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("Edit Dataset: {{name}}", { name: editingDataset?.name ?? "" })}</DialogTitle>
            <DialogDescription>{t("Update dataset description and visibility scope.")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Description")}</label>
              <Input
                placeholder={t("Dataset description")}
                value={datasetEditForm.description}
                onChange={(e) => setDatasetEditForm({ ...datasetEditForm, description: e.target.value })}
              />
            </div>

            {/* Visibility Scope — same as LLM Judge */}
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("Visibility Scope")}</label>
              <select
                value={datasetEditForm.visibility === "public" ? (datasetEditForm.public_scope || "department") : "private"}
                onChange={(e) => {
                  const scope = e.target.value as "private" | "department" | "organization";
                  setDatasetEditForm((prev) => ({
                    ...prev,
                    visibility: scope === "private" ? "private" : "public",
                    public_scope: scope === "private" ? "" : scope,
                    dept_id: scope === "department" ? prev.dept_id : "",
                    public_dept_ids: scope === "department" ? prev.public_dept_ids : [],
                  }));
                }}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="private">{t("Private")}</option>
                <option value="department">{t("Department")}</option>
                <option value="organization">{t("Organization")}</option>
              </select>
            </div>

            {/* Organization — shown for org scope */}
            {datasetEditForm.visibility === "public" && datasetEditForm.public_scope === "organization" && (
              <div className="space-y-2">
                <label className="text-sm font-medium">{t("Organization")}</label>
                <select
                  value={datasetEditForm.org_id}
                  onChange={(e) => setDatasetEditForm({ ...datasetEditForm, org_id: e.target.value })}
                  disabled={isMembershipLockedRole}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-80"
                >
                  {visibilityOptions.organizations.map((org) => (
                    <option key={org.id} value={org.id}>{org.name}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Department — shown for dept scope */}
            {datasetEditForm.visibility === "public" && datasetEditForm.public_scope === "department" && (
              <>
                {canMultiDept && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("Organization")}</label>
                    <select
                      value={datasetEditForm.org_id}
                      onChange={(e) => setDatasetEditForm({ ...datasetEditForm, org_id: e.target.value, public_dept_ids: [] })}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      {visibilityOptions.organizations.map((org) => (
                        <option key={org.id} value={org.id}>{org.name}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="space-y-2">
                  <label className="text-sm font-medium">
                    {canMultiDept ? t("Departments") : t("Department")}
                  </label>
                  {canMultiDept ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm"
                        >
                          <span className="truncate text-left">
                            {getSelectedDeptLabel(datasetEditForm.public_dept_ids, datasetEditForm.org_id)}
                          </span>
                          <ChevronDown className="h-4 w-4 opacity-70" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent className="max-h-64 w-[var(--radix-dropdown-menu-trigger-width)] overflow-y-auto">
                        {visibilityOptions.departments
                          .filter((dept) => !datasetEditForm.org_id || dept.org_id === datasetEditForm.org_id)
                          .map((dept) => (
                            <DropdownMenuCheckboxItem
                              key={dept.id}
                              checked={datasetEditForm.public_dept_ids.includes(dept.id)}
                              onCheckedChange={(checked) =>
                                setDatasetEditForm((prev) => ({
                                  ...prev,
                                  public_dept_ids: checked
                                    ? Array.from(new Set([...prev.public_dept_ids, dept.id]))
                                    : prev.public_dept_ids.filter((id) => id !== dept.id),
                                }))
                              }
                            >
                              {dept.name}
                            </DropdownMenuCheckboxItem>
                          ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : (
                    <select
                      value={datasetEditForm.dept_id}
                      disabled
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-80"
                    >
                      {visibilityOptions.departments.map((dept) => (
                        <option key={dept.id} value={dept.id}>{dept.name}</option>
                      ))}
                    </select>
                  )}
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingDataset(null)}>{t("Cancel")}</Button>
            <Button
              onClick={async () => {
                if (!editingDataset) return;
                try {
                  await updateEvaluationDataset(editingDataset.name, {
                    description: datasetEditForm.description || undefined,
                    visibility: datasetEditForm.visibility,
                    public_scope: datasetEditForm.visibility === "public" ? datasetEditForm.public_scope : undefined,
                    org_id: datasetEditForm.org_id || undefined,
                    dept_id: datasetEditForm.dept_id || undefined,
                    public_dept_ids: datasetEditForm.public_dept_ids.length > 0 ? datasetEditForm.public_dept_ids : undefined,
                  });
                  setEditingDataset(null);
                  fetchDatasets();
                } catch (err: any) {
                  setErrorData({ title: err?.response?.data?.detail || "Failed to update dataset" });
                }
              }}
            >
              Save Changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Trace Detail Dialog — opened when clicking a trace ID in the scores table */}
      <TraceDetailDialog
        selectedTrace={selectedTraceId}
        onClose={() => setSelectedTraceId(null)}
        traceDetail={traceDetail}
        isLoading={traceDetailLoading}
        isFetching={traceDetailLoading}
        isError={traceDetailError}
      />
    </div>
  );
}
