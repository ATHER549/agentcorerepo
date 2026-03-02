import { Play, Plus } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
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
import { useTranslation } from "react-i18next";
import useAlertStore from "@/stores/alertStore";
import { useModelStore } from "@/stores/modelStore";
import {
  createEvaluationDataset,
  createEvaluationDatasetItem,
  createEvaluationScore,
  createEvaluator,
  DatasetExperimentJob,
  deleteEvaluationDataset,
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

export default function EvaluationPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState("judges");
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
  const [datasetForm, setDatasetForm] = useState({ name: "", description: "" });
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
    generation_model_api_key: "",
    evaluator_config_id: "",
    preset_id: "",
    evaluator_name: "",
    criteria: "",
    judge_model: "",
    judge_model_api_key: "",
  });

  // Dialog States
  const [isJudgeDialogOpen, setIsJudgeDialogOpen] = useState(false);
  const [isScoreDialogOpen, setIsScoreDialogOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [runningEvaluatorId, setRunningEvaluatorId] = useState<string | null>(
    null,
  );
  const fetchSeqRef = useRef(0);

  const [modelApiKey, setModelApiKey] = useState<string>("");
  const [agentList, setAgentList] = useState<any[]>([]);
  const storeModels = useModelStore((s) => s.models);
  const [savedModelKeys, setSavedModelKeys] = useState<Record<string, string>>(
    {},
  );

  // Per-tab fetch guards — prevent redundant refetches on every tab revisit
  const hasFetchedScoresRef = useRef(false);
  const hasFetchedDatasetsRef = useRef(false);
  const loadSavedModelKeys = () => {
    try {
      const raw = localStorage.getItem("evaluation_model_keys");
      if (!raw) return {} as Record<string, string>;
      const parsed = JSON.parse(raw || "{}");
      setSavedModelKeys(parsed || {});
      return parsed || {};
    } catch (e) {
      return {} as Record<string, string>;
    }
  };
  const saveModelKey = (modelId: string, key: string) => {
    const next = { ...(savedModelKeys || {}), [modelId]: key };
    setSavedModelKeys(next);
    try {
      localStorage.setItem("evaluation_model_keys", JSON.stringify(next));
    } catch {
      // ignore storage errors
    }
  };

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
    model: "gpt-4o",
    name: "",
    preset_id: "",
    saved_evaluator_id: "",
    model_name: "",
  });
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
      model: "gpt-4o",
      name: "",
      preset_id: "",
      saved_evaluator_id: "",
      model_name: "",
    });
    setGroundTruth("");
    setSelectedAgentIds([]);
    setFilterSessionId("");
    setFilterTraceId("");
    setRunOnNew(true);
    setRunOnExisting(true);
    setScoreForm({ trace_id: "", name: "", value: "0.5", comment: "" });
  };

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
    getAgents()
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
  }, []);

  // Refresh pending traces when opening the Run Judge dialog to ensure dropdown is populated
  useEffect(() => {
    if (!isJudgeDialogOpen) return;
    let mounted = true;
    (async () => {
      try {
        const val = await getPendingReviews({ limit: 100 });
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
        // load saved model API keys and prefill if available
        try {
          const keys = loadSavedModelKeys();
          const modelName =
            (judgeForm.model_name && judgeForm.model_name.trim()) ||
            judgeForm.model;
          if (keys && modelName && keys[modelName]) {
            setModelApiKey(keys[modelName]);
          }
        } catch (e) {
          /* ignore */
        }
      } catch (e) {
        console.error("Failed fetching pending traces:", e);
        setPendingTraces([]);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [isJudgeDialogOpen]);

  // Lazy-load scores data only when the Scores tab becomes active
  useEffect(() => {
    if (activeTab !== "scores") return;
    if (!hasFetchedScoresRef.current) {
      hasFetchedScoresRef.current = true;
      fetchData();
    }
  }, [activeTab]);

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
    } = { limit: 20 };
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
        getPendingReviews({ limit: 20 }),
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
    setIsSubmitting(true);
    try {
      // If both selected, create evaluator targeting both (backend should accept array or handle 'both')
      const targets: string[] = [];
      if (runOnExisting) targets.push("existing");
      if (runOnNew) targets.push("new");

      const modelName =
        (judgeForm.model_name && judgeForm.model_name.trim()) ||
        judgeForm.model;
      const payload: any = {
        name:
          judgeForm.name?.trim() || `LLM Judge - ${new Date().toISOString()}`,
        criteria: judgeForm.criteria || "",
        model: modelName,
        preset_id: judgeForm.preset_id || undefined,
        target: targets.length === 1 ? targets[0] : targets,
      };
      if (groundTruth.trim()) payload.ground_truth = groundTruth.trim();
      if (modelApiKey) {
        payload.model_api_key = modelApiKey;
        // persist locally under the chosen model name
        if (modelName) saveModelKey(modelName, modelApiKey);
      }
      if (selectedAgentIds && selectedAgentIds.length)
        payload.agent_ids = selectedAgentIds;
      if (filterSessionId) payload.session_id = filterSessionId;
      if (filterTraceId) payload.trace_id = filterTraceId;

      // optional filters are currently not exposed in this simplified dialog
      await createEvaluator(payload);
      setIsJudgeDialogOpen(false);
      resetForms();
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

  const handleSaveEvaluator = async () => {
    if (!judgeForm.name || !judgeForm.criteria) {
      setErrorData({ title: "Provide a name and criteria to save evaluator" });
      return;
    }
    if (requiresGroundTruth && !groundTruth.trim()) {
      setErrorData({
        title: "Ground truth is required for the selected preset.",
      });
      return;
    }
    try {
      const targets: string[] = [];
      if (runOnExisting) targets.push("existing");
      if (runOnNew) targets.push("new");
      const modelName =
        (judgeForm.model_name && judgeForm.model_name.trim()) ||
        judgeForm.model;
      const payload: any = {
        name: judgeForm.name,
        criteria: judgeForm.criteria,
        model: modelName,
      };
      if (targets.length === 1) payload.target = targets[0];
      else if (targets.length > 1) payload.target = targets;
      if (judgeForm.preset_id) payload.preset_id = judgeForm.preset_id;
      if (groundTruth.trim()) payload.ground_truth = groundTruth.trim();
      if (selectedAgentIds && selectedAgentIds.length)
        payload.agent_ids = selectedAgentIds;
      if (filterSessionId) payload.session_id = filterSessionId;
      if (filterTraceId) payload.trace_id = filterTraceId;
      if (modelApiKey && modelName) {
        payload.model_api_key = modelApiKey;
        saveModelKey(modelName, modelApiKey);
      }

      if (editingEvaluator) {
        const updated = await updateEvaluator(editingEvaluator, payload);
        setSavedEvaluators((s) =>
          s.map((it) => (it.id === updated.id ? updated : it)),
        );
        setSuccessData({ title: "Evaluator updated" });
        setEditingEvaluator(null);
      } else {
        const created = await createEvaluator(payload);
        // Refresh saved evaluators from server to ensure list is consistent
        try {
          const items = await listEvaluators();
          if (Array.isArray(items)) setSavedEvaluators(items as any);
          else if (items && Array.isArray((items as any).items))
            setSavedEvaluators((items as any).items);
          else if (items && Array.isArray((items as any).data))
            setSavedEvaluators((items as any).data);
        } catch (e) {
          // fallback to adding created item
          setSavedEvaluators((s) => [created, ...s]);
        }
        setSuccessData({ title: "Evaluator saved" });
      }
    } catch (e) {
      setErrorData({ title: "Failed to save evaluator" });
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
      model_name: s.model,
      preset_id: s.preset_id || "",
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
    try {
      const keys = loadSavedModelKeys();
      setModelApiKey((s.model && keys[s.model]) || "");
    } catch {
      setModelApiKey("");
    }
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

  const handleRunSavedEvaluator = async (id: string) => {
    if (!id || runningEvaluatorId === id) return;
    setRunningEvaluatorId(id);
    try {
      const result = await runEvaluator(id);
      const enqueued = Number(result?.enqueued ?? 0);
      if (result?.status === "noop") {
        setNoticeData({
          title:
            result?.message ||
            "Evaluator is configured for new traces only and will run automatically on new traces.",
        });
      } else if (enqueued > 0) {
        setSuccessData({
          title: `Evaluator queued for ${enqueued} existing trace${
            enqueued === 1 ? "" : "s"
          }.`,
        });
      } else {
        setNoticeData({
          title: "No matching existing traces found for this evaluator.",
        });
      }
      await fetchData();
    } catch (error) {
      console.error("Failed to run saved evaluator", error);
      setErrorData({ title: "Failed to run evaluator" });
    } finally {
      setRunningEvaluatorId((current) => (current === id ? null : current));
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
      const created = await createEvaluationDataset({
        name,
        description: datasetForm.description.trim() || undefined,
      });
      setDatasetForm({ name: "", description: "" });
      setSuccessData({ title: t("Dataset '{{name}}' created", { name: created.name }) });
      await fetchDatasets(false);
      setSelectedDatasetName(created.name);
    } catch (error) {
      console.error("Failed to create dataset", error);
      setErrorData({ title: "Failed to create dataset" });
    }
  };

  const handleDeleteDataset = async () => {
    if (!selectedDatasetName) {
      setErrorData({ title: "Select a dataset first" });
      return;
    }
    const confirmed = window.confirm(
      t(
        "Delete dataset '{{name}}'? This will remove all dataset items and experiment runs.",
        { name: selectedDatasetName },
      ),
    );
    if (!confirmed) return;

    try {
      const result = await deleteEvaluationDataset(selectedDatasetName);
      if (result.status === "deleted") {
        setSuccessData({ title: t("Dataset '{{name}}' deleted", { name: selectedDatasetName }) });
      } else {
        setNoticeData({
          title: `Dataset '${selectedDatasetName}' purged (container retained by Langfuse SDK).`,
        });
      }
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
    const generationModel = datasetExperimentForm.generation_model.trim();
    const generationModelApiKey =
      datasetExperimentForm.generation_model_api_key.trim();
    if (!hasAgent && !generationModel) {
      setErrorData({
        title:
          "Select an agent or provide a generation model to run the dataset.",
      });
      return;
    }
    if (!hasAgent && !generationModelApiKey) {
      setErrorData({
        title:
          "Generation model API key is required when running without an agent.",
      });
      return;
    }

    try {
      const datasetNameAtRun = selectedDatasetName;
      const job = await runEvaluationDatasetExperiment(selectedDatasetName, {
        experiment_name: datasetExperimentForm.experiment_name.trim(),
        description: datasetExperimentForm.description.trim() || undefined,
        agent_id: datasetExperimentForm.agent_id || undefined,
        generation_model: hasAgent ? undefined : generationModel || undefined,
        generation_model_api_key: hasAgent
          ? undefined
          : generationModelApiKey || undefined,
        evaluator_config_id:
          datasetExperimentForm.evaluator_config_id || undefined,
        preset_id: datasetExperimentForm.preset_id || undefined,
        evaluator_name:
          datasetExperimentForm.evaluator_name.trim() || undefined,
        criteria: datasetExperimentForm.criteria.trim()
          ? ensureDatasetPromptTemplate(datasetExperimentForm.criteria.trim())
          : undefined,
        judge_model: datasetExperimentForm.judge_model.trim() || undefined,
        judge_model_api_key:
          datasetExperimentForm.judge_model_api_key.trim() || undefined,
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
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center bg-gray-50 dark:bg-gray-800">
          <h3 className="font-medium">Recent Scores</h3>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => fetchData()}>
              Refresh
            </Button>
            <Button
              size="sm"
              onClick={() => setIsScoreDialogOpen(true)}
              className="flex items-center gap-2"
            >
              <Plus className="h-4 w-4" /> Add Score
            </Button>
          </div>
        </div>
        <div className="p-4 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Input
              placeholder="Filter by Trace ID"
              value={scoreFilters.trace_id}
              onChange={(e) =>
                setScoreFilters({ ...scoreFilters, trace_id: e.target.value })
              }
            />
            <Input
              placeholder="Filter by Metric Name"
              value={scoreFilters.name}
              onChange={(e) =>
                setScoreFilters({ ...scoreFilters, name: e.target.value })
              }
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={() => fetchData()} className="flex-1">
                Apply Filters
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
                Clear
              </Button>
            </div>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
              <tr>
                <th className="px-6 py-3">Timestamp</th>
                <th className="px-6 py-3">Trace ID</th>
                <th className="px-6 py-3">Agent Name</th>
                <th className="px-6 py-3">Metric</th>
                <th className="px-6 py-3">Evaluation Score</th>
                <th className="px-6 py-3">Source</th>
                <th className="px-6 py-3">Comment</th>
              </tr>
            </thead>
            <tbody>
              {recentScores.map((score) => (
                <tr
                  key={
                    score.id ??
                    `${score.trace_id}-${score.name}-${score.created_at ?? ""}`
                  }
                  className="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <td className="px-6 py-4">
                    {score.created_at
                      ? new Date(score.created_at).toLocaleString()
                      : "-"}
                  </td>
                  <td className="px-6 py-4 font-mono text-xs text-blue-600 dark:text-blue-400">
                    <span title={score.trace_id}>{score.trace_id || "-"}</span>
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
                    <span className="px-2 py-1 rounded text-xs bg-gray-100 dark:bg-gray-700">
                      {score.source}
                    </span>
                  </td>
                  <td
                    className="px-6 py-4 text-gray-500 truncate max-w-xs"
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
                    className="px-6 py-8 text-center text-gray-500"
                  >
                    No evaluation scores found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderDatasets = () => {
    const agentOptions = (agentList || [])
      .map((agent: any) => {
        const id = agent?.metadata?.agent_id || agent?.id;
        if (!id) return null;
        return {
          id: String(id),
          label: agent?.metadata?.display_name || agent?.name || String(id),
        };
      })
      .filter(Boolean) as Array<{ id: string; label: string }>;

    return (
      <div className="flex flex-col gap-6">
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-medium">Dataset Management</h3>
            <div className="flex items-center gap-2">
              {selectedDatasetName ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleDeleteDataset}
                >
                  Delete Dataset
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="outline"
                onClick={() => fetchDatasets(true)}
                disabled={datasetsLoading}
              >
                {datasetsLoading ? "Refreshing..." : "Refresh"}
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
                Clear Selection
              </Button>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-2">
              <label className="text-sm font-medium">Select Dataset</label>
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
                  <SelectValue placeholder="Choose dataset" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">None (unselected)</SelectItem>
                  {datasets.map((dataset) => (
                    <SelectItem key={dataset.id || dataset.name} value={dataset.name}>
                      {dataset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">New Dataset Name</label>
              <Input
                placeholder="e.g. support-faq-v1"
                value={datasetForm.name}
                onChange={(e) =>
                  setDatasetForm({ ...datasetForm, name: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Input
                placeholder="Optional description"
                value={datasetForm.description}
                onChange={(e) =>
                  setDatasetForm({
                    ...datasetForm,
                    description: e.target.value,
                  })
                }
              />
            </div>
          </div>
          <div className="mt-4">
            <Button size="sm" onClick={handleCreateDataset}>
              <Plus className="h-4 w-4 mr-1" /> Create Dataset
            </Button>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
          <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h3 className="font-medium">Dataset List</h3>
            <span className="text-xs text-gray-500">
              {datasets.length} dataset{datasets.length === 1 ? "" : "s"}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                <tr>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3">Items</th>
                  <th className="px-4 py-3">Updated</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((dataset) => {
                  const isSelected = selectedDatasetName === dataset.name;
                  return (
                    <tr
                      key={dataset.id || dataset.name}
                      className={`border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer ${
                        isSelected ? "bg-red-50 dark:bg-red-950/30" : ""
                      }`}
                      onClick={() => void handleOpenDatasetItemsDialog(dataset.name)}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <span className="font-medium">{dataset.name}</span>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleOpenDatasetItemsDialog(dataset.name);
                            }}
                          >
                            View
                          </Button>
                        </div>
                      </td>
                      <td
                        className="px-4 py-3 max-w-xl truncate"
                        title={dataset.description || ""}
                      >
                        {dataset.description || "-"}
                      </td>
                      <td className="px-4 py-3">{dataset.item_count ?? "-"}</td>
                      <td className="px-4 py-3">
                        {dataset.updated_at
                          ? new Date(dataset.updated_at).toLocaleString()
                          : "-"}
                      </td>
                    </tr>
                  );
                })}
                {datasets.length === 0 && (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-4 py-6 text-center text-gray-500"
                    >
                      No datasets found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
          <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h3 className="font-medium">Run Experiment</h3>
            <Button
              size="sm"
              variant="outline"
              onClick={() => fetchDatasetDetails(selectedDatasetName)}
              disabled={!selectedDatasetName}
            >
              Refresh Runs
            </Button>
          </div>
          <div className="p-4 border-b border-gray-200 dark:border-gray-700 grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-2">
              <label className="text-sm font-medium">Experiment Name</label>
              <Input
                placeholder="e.g. Agent v2 Regression"
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
              <label className="text-sm font-medium">Agent</label>
              <Select
                value={datasetExperimentForm.agent_id || "__none__"}
                onValueChange={(value) => {
                  const nextAgentId = value === "__none__" ? "" : value;
                  const selectedAgent = agentOptions.find(
                    (agent) => agent.id === nextAgentId,
                  );
                  const nextExperimentName =
                    selectedAgent?.label ||
                    datasetExperimentForm.experiment_name;
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    agent_id: nextAgentId,
                    experiment_name: nextAgentId
                      ? nextExperimentName
                      : datasetExperimentForm.experiment_name,
                  });
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Choose agent (optional)" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">
                    No agent (use generation model)
                  </SelectItem>
                  {agentOptions.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {!datasetExperimentForm.agent_id ? (
              <>
                <div className="space-y-2">
                  <label className="text-sm font-medium">
                    Generation Model
                  </label>
                  <Input
                    placeholder="e.g. gpt-4o-mini"
                    value={datasetExperimentForm.generation_model}
                    onChange={(e) =>
                      setDatasetExperimentForm({
                        ...datasetExperimentForm,
                        generation_model: e.target.value,
                      })
                    }
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">
                    Generation Model API Key
                  </label>
                  <Input
                    placeholder="sk-..."
                    value={datasetExperimentForm.generation_model_api_key}
                    onChange={(e) =>
                      setDatasetExperimentForm({
                        ...datasetExperimentForm,
                        generation_model_api_key: e.target.value,
                      })
                    }
                  />
                </div>
              </>
            ) : null}
            <div className="space-y-2">
              <label className="text-sm font-medium">Use Saved Evaluator</label>
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
                  <SelectValue placeholder="Optional evaluator" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">None</SelectItem>
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
                Evaluator Template (Preset)
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
                  <SelectValue placeholder="Choose preset template" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">None</SelectItem>
                  {presets.map((preset) => (
                    <SelectItem key={preset.id} value={preset.id}>
                      {preset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedDatasetPreset?.requires_ground_truth ? (
                <p className="text-xs text-amber-600">
                  This preset requires ground truth in dataset item expected
                  outputs.
                </p>
              ) : null}
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Evaluator Name</label>
              <Input
                placeholder="e.g. correctness"
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
                Judge Model (Optional)
              </label>
              <Input
                placeholder="e.g. gpt-4o"
                value={datasetExperimentForm.judge_model}
                onChange={(e) =>
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    judge_model: e.target.value,
                  })
                }
              />
            </div>
            <div className="space-y-2 md:col-span-2">
              <label className="text-sm font-medium">
                Evaluation Criteria Prompt
              </label>
              <textarea
                className="flex min-h-[88px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                placeholder="Prompt used by the evaluator"
                value={datasetExperimentForm.criteria}
                onChange={(e) =>
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    criteria: e.target.value,
                  })
                }
              />
              <p className="text-xs text-gray-500">
                Keep placeholders in prompt: <code>{"{{query}}"}</code>,{" "}
                <code>{"{{generation}}"}</code>,{" "}
                <code>{"{{ground_truth}}"}</code>.
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">
                Judge Model API Key (Optional)
              </label>
              <Input
                placeholder="sk-..."
                value={datasetExperimentForm.judge_model_api_key}
                onChange={(e) =>
                  setDatasetExperimentForm({
                    ...datasetExperimentForm,
                    judge_model_api_key: e.target.value,
                  })
                }
              />
            </div>
            <div className="space-y-2 md:col-span-3">
              <label className="text-sm font-medium">
                Description (Optional)
              </label>
              <Input
                placeholder="Experiment notes"
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
                <Play className="h-4 w-4 mr-1" /> Run Experiment
              </Button>
            </div>
          </div>
          {datasetExperimentJob && (
            <div className="p-4 border-b border-gray-200 dark:border-gray-700 text-sm">
              <span className="font-medium">Latest Job:</span>{" "}
              <span className="font-mono">{datasetExperimentJob.job_id}</span>{" "}
              <span className="ml-2">
                Status: {datasetExperimentJob.status}
              </span>
              {datasetExperimentJob.status === "queued" ||
              datasetExperimentJob.status === "running" ? (
                <div className="mt-3">
                  <div className="h-2 w-full rounded bg-gray-200 dark:bg-gray-700 overflow-hidden">
                    <div className="h-full w-1/3 bg-[#da2128] animate-pulse" />
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    Experiment "{datasetExperimentJob.experiment_name}" is
                    running in background.
                  </div>
                </div>
              ) : null}
              {datasetExperimentJob.status === "completed" ? (
                <div className="mt-2 text-xs text-green-700 dark:text-green-400">
                  Experiment "{datasetExperimentJob.experiment_name}" completed.
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
              <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                <tr>
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">Run ID</th>
                  <th className="px-4 py-3">Run Name</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {datasetRuns.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                    onClick={() => handleOpenRunDetail(run)}
                  >
                    <td className="px-4 py-3">
                      {run.created_at
                        ? new Date(run.created_at).toLocaleString()
                        : "-"}
                    </td>
                    <td
                      className="px-4 py-3 font-mono text-xs text-blue-600 dark:text-blue-400"
                      title="Click to view run details"
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
                          View
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteDatasetRun(run);
                          }}
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {datasetRuns.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-4 py-6 text-center text-gray-500"
                    >
                      No experiment runs found.
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
      <div className="flex flex-none flex-col justify-between border-b px-6 py-4">
        <div className="flex flex-col gap-1">
          <h2 className="text-2xl font-semibold tracking-tight">Evaluation</h2>
          <p className="text-sm text-muted-foreground">
            Monitor quality metrics, run LLM judges, and review traces.
          </p>
        </div>
      </div>
      <div className="flex-1 overflow-hidden p-6">
        <div className="flex flex-col h-full w-full max-w-[1600px] mx-auto">
          {/* Tabs Header */}
          <div className="flex border-b border-gray-200 dark:border-gray-700 mb-6">
            <button
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "judges"
                  ? "border-[#da2128] text-[#da2128]"
                  : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300"
              }`}
              onClick={() => setActiveTab("judges")}
            >
              LLM Judges
            </button>
            <button
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "datasets"
                  ? "border-[#da2128] text-[#da2128]"
                  : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300"
              }`}
              onClick={() => setActiveTab("datasets")}
            >
              Datasets
            </button>
            <button
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "scores"
                  ? "border-[#da2128] text-[#da2128]"
                  : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300"
              }`}
              onClick={() => setActiveTab("scores")}
            >
              Scores
            </button>
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-auto">
            <>
              {activeTab === "scores" && (
                loading ? (
                  <div className="flex flex-col items-center justify-center h-64 gap-3">
                    <div
                      className="animate-spin rounded-full h-8 w-8 border-2 border-gray-200"
                      style={{ borderTopColor: "#da2128" }}
                    />
                    <p className="text-sm text-gray-500">Loading scores…</p>
                  </div>
                ) : renderScoresList()
              )}
              {activeTab === "judges" && (
                  <div className="flex flex-col gap-6">
                    <div className="p-8 text-center bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                      <h3 className="text-lg font-medium mb-2">
                        LLM Judges Configuration
                      </h3>
                      <p className="text-gray-500 mb-6">
                        Configure automated evaluators to grade your traces
                        based on custom criteria.
                      </p>
                      {status && !status.langfuse_available && (
                        <p className="text-sm text-red-600 dark:text-red-400 mb-4">
                          Langfuse is not configured. Please set LANGFUSE_*
                          environment variables.
                        </p>
                      )}
                      {status && !status.llm_judge_available && (
                        <p className="text-sm text-amber-600 dark:text-amber-400 mb-4">
                          LLM Judge is unavailable. Please install LiteLLM in
                          the backend.
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
                        Create New Judge
                      </button>
                    </div>

                    {/* Saved Evaluators List */}
                    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
                      <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center bg-gray-50 dark:bg-gray-800">
                        <h3 className="font-medium">Saved Evaluators</h3>
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
                            Refresh
                          </Button>
                        </div>
                      </div>
                      <div className="overflow-x-auto p-4">
                        {savedEvaluators.length === 0 ? (
                          <div className="text-sm text-gray-500">
                            No saved evaluators.
                          </div>
                        ) : (
                          <table className="w-full text-sm text-left">
                            <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                              <tr>
                                <th className="px-4 py-2">Name</th>
                                <th className="px-4 py-2">Model</th>
                                <th className="px-4 py-2">Criteria</th>
                                <th className="px-4 py-2">Action</th>
                              </tr>
                            </thead>
                            <tbody>
                              {savedEvaluators.map((ev) => (
                                <tr
                                  key={ev.id}
                                  className="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700"
                                >
                                  <td className="px-4 py-3 font-medium">
                                    {ev.name}
                                  </td>
                                  <td className="px-4 py-3">{ev.model}</td>
                                  <td
                                    className="px-4 py-3 truncate max-w-xl"
                                    title={ev.criteria}
                                  >
                                    {ev.criteria}
                                  </td>
                                  <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                      <Button
                                        size="sm"
                                        onClick={() =>
                                          handleEditEvaluator(ev.id)
                                        }
                                      >
                                        Edit
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() =>
                                          handleRunSavedEvaluator(ev.id)
                                        }
                                        disabled={runningEvaluatorId === ev.id}
                                      >
                                        {runningEvaluatorId === ev.id
                                          ? "Running..."
                                          : "Run"}
                                      </Button>
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
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    </div>

                    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
                      <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center bg-gray-50 dark:bg-gray-800">
                        <h3 className="font-medium">Pending Traces</h3>
                        <Button
                          size="sm"
                          onClick={() => fetchData()}
                          variant="outline"
                        >
                          Refresh
                        </Button>
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                          <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                            <tr>
                              <th className="px-6 py-3">Trace ID</th>
                              <th className="px-6 py-3">Name</th>
                              <th className="px-6 py-3">agent</th>
                              <th className="px-6 py-3">Scores</th>
                              <th className="px-6 py-3">Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {safePendingTraces.map((trace) => (
                              <tr
                                key={trace.id}
                                className="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700"
                              >
                                <td className="px-6 py-4 font-mono text-xs text-blue-600 dark:text-blue-400">
                                  {shortId(trace.id)}
                                </td>
                                <td className="px-6 py-4">
                                  {trace.name || "-"}
                                </td>
                                <td className="px-6 py-4">
                                  {trace.agent_name || "-"}
                                </td>
                                <td className="px-6 py-4">
                                  {trace.has_scores
                                    ? `${trace.score_count} scores`
                                    : "No scores"}
                                </td>
                                <td className="px-6 py-4">
                                  <Button
                                    size="sm"
                                    onClick={() => {
                                      setJudgeForm({
                                        ...judgeForm,
                                        trace_id: trace.id,
                                      });
                                      setIsJudgeDialogOpen(true);
                                    }}
                                  >
                                    Judge
                                  </Button>
                                </td>
                              </tr>
                            ))}
                            {safePendingTraces.length === 0 && (
                              <tr>
                                <td
                                  colSpan={5}
                                  className="px-6 py-8 text-center text-gray-500"
                                >
                                  No pending traces found.
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
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
      <Dialog open={isJudgeDialogOpen} onOpenChange={setIsJudgeDialogOpen}>
        <DialogContent className="max-w-2xl w-full">
          <DialogHeader>
            <DialogTitle>Run LLM Judge</DialogTitle>
            <DialogDescription>
              Evaluate a specific trace using an LLM based on your criteria.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <p className="text-sm text-gray-600">
                Choose where the evaluator should run.
              </p>
            </div>
            <div className="space-y-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={runOnNew}
                  onChange={(e) => setRunOnNew(e.target.checked)}
                  className="form-checkbox"
                />
                <span className="text-sm">Run on New Traces</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={runOnExisting}
                  onChange={(e) => setRunOnExisting(e.target.checked)}
                  className="form-checkbox"
                />
                <span className="text-sm">Run on Existing Traces</span>
              </label>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-2">
                <label className="text-sm font-medium">Use a Preset</label>
                <Select
                  value={judgeForm.preset_id}
                  onValueChange={(val) => {
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
                    <SelectValue placeholder="Choose a preset" />
                  </SelectTrigger>
                  <SelectContent>
                    {presets.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedPreset?.requires_ground_truth && (
                  <p className="text-xs text-amber-600">
                    This preset requires ground truth.
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Agents</label>
                <div className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm max-h-44 overflow-y-auto">
                  {agentList && agentList.length > 0 ? (
                    agentList.map((f: any) => {
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
                      const checked = selectedAgentIds.includes(fid);
                      return (
                        <label
                          key={fid}
                          className="flex items-center gap-2 py-1"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedAgentIds((s) =>
                                  Array.from(new Set([...s, fid])),
                                );
                              } else {
                                setSelectedAgentIds((s) =>
                                  s.filter((x) => x !== fid),
                                );
                              }
                            }}
                            className="form-checkbox"
                          />
                          <span className="text-sm">{label}</span>
                        </label>
                      );
                    })
                  ) : (
                    <div className="text-sm text-gray-500 py-2">
                      No agents available
                    </div>
                  )}
                </div>
                <p className="text-xs text-gray-500">
                  Select one or more agents (agents) to target.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-2">
                <label className="text-sm font-medium">Judge Model Name</label>
                <Input
                  placeholder="e.g. gpt-4o or custom"
                  value={judgeForm.model_name}
                  onChange={(e) =>
                    setJudgeForm({ ...judgeForm, model_name: e.target.value })
                  }
                />
                <p className="text-xs text-gray-500">
                  Name of the LLM to use as judge. If empty, a default model
                  will be used.
                </p>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">
                  Model API Key (optional)
                </label>
                <div className="flex gap-2">
                  <Input
                    placeholder="sk-..."
                    value={modelApiKey}
                    onChange={(e) => setModelApiKey(e.target.value)}
                  />
                </div>
                <p className="text-xs text-gray-500">
                  API key is stored locally in your browser only and will be
                  saved when you Save or Run the evaluator.
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Evaluation Criteria</label>
              <textarea
                className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder="e.g. Is the answer helpful and accurate?"
                value={judgeForm.criteria}
                onChange={(e) =>
                  setJudgeForm({ ...judgeForm, criteria: e.target.value })
                }
              />
            </div>

            {requiresGroundTruth && (
              <div className="space-y-2">
                <label className="text-sm font-medium">Ground Truth</label>
                <textarea
                  className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  placeholder="Provide expected answer/output used as reference for evaluation."
                  value={groundTruth}
                  onChange={(e) => setGroundTruth(e.target.value)}
                />
              </div>
            )}

            <div className="flex gap-2">
              <Button variant="outline" onClick={handleSaveEvaluator}>
                Save Evaluator
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setEditingEvaluator(null);
                setIsJudgeDialogOpen(false);
              }}
            >
              Cancel
            </Button>
            <Button onClick={handleRunJudge} disabled={isSubmitting}>
              {isSubmitting ? "Starting..." : "Run Evaluation"}
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
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      key={datasetCsvInputKey}
                      type="file"
                      accept=".csv,text/csv"
                      onChange={(e) =>
                        setDatasetCsvFile(e.target.files?.[0] || null)
                      }
                      className="block w-full max-w-md text-sm file:mr-3 file:rounded-md file:border file:border-gray-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-gray-50"
                    />
                    <Button
                      size="sm"
                      onClick={handleUploadDatasetCsv}
                      disabled={!datasetCsvFile || datasetCsvUploading}
                    >
                      {datasetCsvUploading ? t("Uploading...") : t("Upload CSV")}
                    </Button>
                  </div>
                  <p className="text-xs text-gray-500">
                    {t("Supported headers:")} <code>input</code>,{" "}
                    <code>expected_output</code>, <code>metadata</code>,{" "}
                    <code>trace_id</code>, <code>source_trace_id</code>.
                  </p>
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
                <div className="p-4 border-b border-gray-200 dark:border-gray-700 grid grid-cols-1 md:grid-cols-2 gap-3">
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
                      placeholder="Trace ID reference"
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
                    <Button size="sm" onClick={handleAddDatasetItem}>
                      <Plus className="h-4 w-4 mr-1" /> Add Dataset Item
                    </Button>
                  </div>
                </div>
                <div className="max-h-[420px] overflow-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                      <tr>
                        <th className="px-4 py-3">Timestamp</th>
                        <th className="px-4 py-3">Item ID</th>
                        <th className="px-4 py-3">Trace ID</th>
                        <th className="px-4 py-3">Input</th>
                        <th className="px-4 py-3">Expected Output</th>
                        <th className="px-4 py-3">Metadata</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {datasetItems.map((item) => (
                        <tr
                          key={item.id}
                          className="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700"
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
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleDeleteDatasetItem(item.id)}
                            >
                              Delete
                            </Button>
                          </td>
                        </tr>
                      ))}
                      {datasetItems.length === 0 && (
                        <tr>
                          <td
                            colSpan={8}
                            className="px-4 py-6 text-center text-gray-500"
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
            <div className="flex-1 overflow-y-auto px-6 py-8 text-center text-sm text-gray-500">
              Select a dataset from the dataset list.
            </div>
          )}
          <DialogFooter className="px-6 pb-6 pt-3 border-t border-gray-200 dark:border-gray-700">
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
            <DialogTitle>Dataset Run Details</DialogTitle>
            <DialogDescription>
              Inspect traces and scores generated for this experiment run.
            </DialogDescription>
          </DialogHeader>
          {runDetailLoading ? (
            <div className="flex flex-col items-center justify-center py-10 gap-3">
              <div
                className="animate-spin rounded-full h-8 w-8 border-2 border-gray-200"
                style={{ borderTopColor: "#da2128" }}
              />
              <p className="text-sm text-gray-500">Loading run details…</p>
            </div>
          ) : selectedRunDetail ? (
            <div className="space-y-4 py-2">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                <div className="rounded border p-3">
                  <div className="text-xs text-gray-500">Run ID</div>
                  <div className="font-mono break-all">
                    {selectedRunDetail.run.id}
                  </div>
                </div>
                <div className="rounded border p-3">
                  <div className="text-xs text-gray-500">Run Name</div>
                  <div>{selectedRunDetail.run.name}</div>
                </div>
                <div className="rounded border p-3">
                  <div className="text-xs text-gray-500">Items</div>
                  <div>{selectedRunDetail.item_count}</div>
                </div>
              </div>

              <div className="max-h-[420px] overflow-auto border rounded">
                <table className="w-full text-sm text-left">
                  <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                    <tr>
                      <th className="px-4 py-3">Run Item ID</th>
                      <th className="px-4 py-3">Trace ID</th>
                      <th className="px-4 py-3">Trace Name</th>
                      <th className="px-4 py-3">Input</th>
                      <th className="px-4 py-3">Output</th>
                      <th className="px-4 py-3">Scores</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRunDetail.items.map((item) => (
                      <tr
                        key={item.id}
                        className="border-b dark:border-gray-700 align-top"
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
                                <div className="text-xs text-gray-500">
                                  +{item.scores.length - 4} more
                                </div>
                              ) : null}
                            </div>
                          ) : (
                            <span className="text-xs text-gray-500">
                              No scores
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {selectedRunDetail.items.length === 0 && (
                      <tr>
                        <td
                          colSpan={6}
                          className="px-4 py-6 text-center text-gray-500"
                        >
                          No run items found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="py-8 text-center text-sm text-gray-500">
              No run details available.
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsRunDetailOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create Score Dialog */}
      <Dialog open={isScoreDialogOpen} onOpenChange={setIsScoreDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Manual Score</DialogTitle>
            <DialogDescription>Manually evaluate a trace.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Trace ID</label>
              <Input
                placeholder="Trace ID"
                value={scoreForm.trace_id}
                onChange={(e) =>
                  setScoreForm({ ...scoreForm, trace_id: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Metric Name</label>
              <Input
                placeholder="e.g. Accuracy, User Satisfaction"
                value={scoreForm.name}
                onChange={(e) =>
                  setScoreForm({ ...scoreForm, name: e.target.value })
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Score (0.0 - 1.0)</label>
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
              <label className="text-sm font-medium">Comment (Optional)</label>
              <Input
                placeholder="Reasoning..."
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
              Cancel
            </Button>
            <Button onClick={handleCreateScore} disabled={isSubmitting}>
              {isSubmitting ? "Saving..." : "Save Score"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
