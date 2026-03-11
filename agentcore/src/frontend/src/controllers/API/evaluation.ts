import { api } from "./api";

export interface Score {
  id: string;
  trace_id: string;
  agent_name?: string;
  name: string;
  value: number;
  source: string;
  comment?: string;
  created_at?: string;
  user_id?: string;
}

export interface EvaluationStatus {
  langfuse_available: boolean;
  llm_judge_available: boolean;
  user_id?: string;
}

export interface TraceForReview {
  id: string;
  name?: string | null;
  timestamp?: string | null;
  input?: unknown;
  output?: unknown;
  session_id?: string | null;
  agent_name?: string | null;
  has_scores: boolean;
  score_count: number;
}

export interface EvaluationDataset {
  id: string;
  name: string;
  description?: string | null;
  metadata?: unknown;
  created_at?: string | null;
  updated_at?: string | null;
  item_count?: number | null;
  visibility?: "private" | "public";
  public_scope?: "organization" | "department" | null;
  owner_user_id?: string | null;
  org_id?: string | null;
  dept_id?: string | null;
  public_dept_ids?: string[] | null;
}

export interface EvaluationDatasetItem {
  id: string;
  dataset_name: string;
  status?: string | null;
  input?: unknown;
  expected_output?: unknown;
  metadata?: unknown;
  source_trace_id?: string | null;
  source_observation_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface EvaluationDatasetRun {
  id: string;
  name: string;
  description?: string | null;
  metadata?: unknown;
  dataset_id?: string | null;
  dataset_name?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface EvaluationDatasetRunItemScore {
  id: string;
  name: string;
  value: number;
  source: string;
  comment?: string | null;
  created_at?: string | null;
}

export interface EvaluationDatasetRunItemDetail {
  id: string;
  dataset_item_id?: string | null;
  trace_id?: string | null;
  observation_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  trace_name?: string | null;
  trace_input?: unknown;
  trace_output?: unknown;
  score_count: number;
  scores: EvaluationDatasetRunItemScore[];
}

export interface EvaluationDatasetRunDetail {
  run: EvaluationDatasetRun;
  item_count: number;
  items: EvaluationDatasetRunItemDetail[];
}

export interface DatasetCsvImportError {
  row: number;
  message: string;
}

export interface DatasetCsvImportResponse {
  dataset_name: string;
  total_rows: number;
  created_count: number;
  failed_count: number;
  skipped_count: number;
  errors: DatasetCsvImportError[];
}

export interface DatasetExperimentJob {
  job_id: string;
  status: string;
  dataset_name: string;
  experiment_name: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  result?: {
    dataset_run_id?: string | null;
    dataset_run_url?: string | null;
    run_name?: string | null;
    item_count?: number;
    metrics?: Record<
      string,
      { count: number; avg: number; min: number; max: number }
    >;
  } | null;
}

export const getEvaluationScores = async (params: {
  limit?: number;
  page?: number;
  trace_id?: string;
  name?: string;
  environment?: string;
}) => {
  const response = await api.get("/api/evaluation/scores", { params });
  return response.data;
};

export const createEvaluationScore = async (data: {
  trace_id: string;
  name: string;
  value: number;
  comment?: string;
  observation_id?: string;
}) => {
  const response = await api.post("/api/evaluation/create", data);
  return response.data;
};

export const getEvaluationStatus = async () => {
  const response = await api.get("/api/evaluation/status");
  return response.data;
};

export const getPendingReviews = async (
  params: {
    limit?: number;
    trace_id?: string;
    agent_name?: string;
    session_id?: string;
    user_id_filter?: string;
    ts_from?: string;
    ts_to?: string;
    environment?: string;
  } = { limit: 20 },
) => {
  const response = await api.get("/api/evaluation/traces/pending", { params });
  return response.data;
};

export const getEvaluationDatasets = async (
  params: { limit?: number; page?: number; search?: string } = { limit: 50 },
) => {
  const response = await api.get("/api/evaluation/datasets", { params });
  return response.data as {
    items: EvaluationDataset[];
    total: number;
    page: number;
    limit: number;
  };
};

export const createEvaluationDataset = async (data: {
  name: string;
  description?: string;
  metadata?: unknown;
  visibility?: string;
  public_scope?: string;
  org_id?: string;
  dept_id?: string;
  public_dept_ids?: string[];
}) => {
  const response = await api.post("/api/evaluation/datasets", data);
  return response.data as EvaluationDataset;
};

export const deleteEvaluationDataset = async (datasetName: string) => {
  const response = await api.delete(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}`,
  );
  return response.data as {
    status: "deleted" | "purged";
    dataset_name: string;
    dataset_deleted: boolean;
    runs_deleted: number;
    items_deleted: number;
    errors?: string[];
  };
};

export const getEvaluationDatasetItems = async (
  datasetName: string,
  params: {
    limit?: number;
    page?: number;
    source_trace_id?: string;
  } = { limit: 50 },
) => {
  const response = await api.get(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}/items`,
    { params },
  );
  return response.data as {
    items: EvaluationDatasetItem[];
    total: number;
    page: number;
    limit: number;
  };
};

export const createEvaluationDatasetItem = async (
  datasetName: string,
  data: {
    input?: unknown;
    expected_output?: unknown;
    metadata?: unknown;
    source_trace_id?: string;
    source_observation_id?: string;
    trace_id?: string;
    use_trace_output_as_expected?: boolean;
  },
) => {
  const response = await api.post(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}/items`,
    data,
  );
  return response.data as EvaluationDatasetItem;
};

export const uploadEvaluationDatasetItemsCsv = async (
  datasetName: string,
  file: File,
) => {
  const formData = new FormData();
  formData.append("csv_file", file);
  const response = await api.post(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}/items/upload-csv`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    },
  );
  return response.data as DatasetCsvImportResponse;
};

export const deleteEvaluationDatasetItem = async (
  datasetName: string,
  itemId: string,
) => {
  const response = await api.delete(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}/items/${encodeURIComponent(itemId)}`,
  );
  return response.data as {
    status: string;
    dataset_name: string;
    item_id: string;
  };
};

export const getEvaluationDatasetRuns = async (
  datasetName: string,
  params: {
    limit?: number;
    page?: number;
  } = { limit: 50 },
) => {
  const response = await api.get(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}/runs`,
    { params },
  );
  return response.data as {
    items: EvaluationDatasetRun[];
    total: number;
    page: number;
    limit: number;
  };
};

export const getEvaluationDatasetRunDetail = async (
  datasetName: string,
  runId: string,
  params: {
    item_limit?: number;
    score_limit?: number;
  } = { item_limit: 50, score_limit: 20 },
) => {
  const response = await api.get(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}/runs/${encodeURIComponent(runId)}`,
    { params },
  );
  return response.data as EvaluationDatasetRunDetail;
};

export const deleteEvaluationDatasetRun = async (
  datasetName: string,
  runId: string,
) => {
  const response = await api.delete(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}/runs/${encodeURIComponent(runId)}`,
  );
  return response.data as {
    status: string;
    dataset_name: string;
    run_id: string;
    run_name?: string;
  };
};

export const runEvaluationDatasetExperiment = async (
  datasetName: string,
  data: {
    experiment_name: string;
    description?: string;
    agent_id?: string;
    generation_model_registry_id?: string;
    evaluator_config_id?: string;
    preset_id?: string;
    evaluator_name?: string;
    criteria?: string;
    judge_model_registry_id?: string;
  },
) => {
  const response = await api.post(
    `/api/evaluation/datasets/${encodeURIComponent(datasetName)}/experiments`,
    data,
  );
  return response.data as {
    job_id: string;
    dataset_name: string;
    experiment_name: string;
    status: string;
  };
};

export const getDatasetExperimentJob = async (jobId: string) => {
  const response = await api.get(
    `/api/evaluation/datasets/experiments/${encodeURIComponent(jobId)}`,
  );
  return response.data as DatasetExperimentJob;
};

export interface EvaluatorConfig {
  id: string;
  name: string;
  criteria: string;
  model: string;
  model_registry_id?: string;
  user_id?: string;
  org_id?: string;
  dept_id?: string;
  preset_id?: string;
  target?: string[];
  ground_truth?: string;
  trace_id?: string;
  agent_id?: string;
  agent_ids?: string[];
  agent_name?: string;
  session_id?: string;
  project_name?: string;
  ts_from?: string;
  ts_to?: string;
  created_at?: string;
  visibility?: "private" | "public";
  public_scope?: "organization" | "department" | null;
  shared_user_ids?: string[];
  public_dept_ids?: string[];
}

export interface EvaluationPreset {
  id: string;
  name: string;
  description?: string;
  criteria: string;
  requires_ground_truth?: boolean;
}

export const createEvaluator = async (data: any, params?: { environment?: string }) => {
  const response = await api.post("/api/evaluation/configs", data, { params });
  return response.data as EvaluatorConfig;
};

export const getAgents = async (params?: { environment?: string }) => {
  const response = await api.get("/api/evaluation/models", { params });
  return response.data;
};

export const listEvaluators = async () => {
  const response = await api.get("/api/evaluation/configs");
  return response.data as EvaluatorConfig[];
};

export const getEvaluationPresets = async () => {
  const response = await api.get("/api/evaluation/presets");
  return response.data as EvaluationPreset[];
};

export const runEvaluator = async (id: string, params?: { environment?: string }) => {
  const response = await api.post(`/api/evaluation/configs/${id}/run`, undefined, { params });
  return response.data as {
    status: "queued" | "noop";
    config_id: string;
    enqueued: number;
    target?: string[];
    message?: string;
  };
};

export const getAvailableModels = async () => {
  // Use the backend evaluation models proxy which uses standard app auth (cookie/JWT)
  const response = await api.get("/api/evaluation/models");
  // returns { object: 'list', data: [...] }
  return response.data;
};

export const updateEvaluator = async (id: string, data: any) => {
  const response = await api.put(`/api/evaluation/configs/${id}`, data);
  return response.data as EvaluatorConfig;
};

export const deleteEvaluator = async (id: string) => {
  const response = await api.delete(`/api/evaluation/configs/${id}`);
  return response.data as { status: string };
};
