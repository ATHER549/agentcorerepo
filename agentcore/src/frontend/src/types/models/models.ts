export type ModelProvider =
  | "openai"
  | "azure"
  | "anthropic"
  | "google"
  | "groq"
  | "openai_compatible";

export type ModelEnvironment = "test" | "uat" | "prod";
export type ModelVisibilityScope = "private" | "department" | "organization";

export type ModelTypeFilter = "llm" | "embedding";

export interface ModelCapabilities {
  supports_streaming?: boolean;
  supports_thinking?: boolean;
  supports_vision?: boolean;
  supports_tool_calling?: boolean;
  context_window?: number;
}

export interface ModelType {
  id: string;
  display_name: string;
  description?: string | null;
  provider: ModelProvider;
  model_name: string;
  model_type: ModelTypeFilter;
  base_url?: string | null;
  environment: ModelEnvironment;
  visibility_scope?: ModelVisibilityScope;
  org_id?: string | null;
  dept_id?: string | null;
  public_dept_ids?: string[] | null;
  approval_status?: "pending" | "approved" | "rejected";
  has_api_key: boolean;
  provider_config?: Record<string, any> | null;
  capabilities?: ModelCapabilities | null;
  default_params?: Record<string, any> | null;
  is_active: boolean;
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface ModelCreateRequest {
  display_name: string;
  description?: string | null;
  provider: string;
  model_name: string;
  model_type?: ModelTypeFilter;
  base_url?: string | null;
  api_key?: string | null;
  environment?: ModelEnvironment;
  visibility_scope?: ModelVisibilityScope;
  org_id?: string | null;
  dept_id?: string | null;
  public_dept_ids?: string[] | null;
  provider_config?: Record<string, any> | null;
  capabilities?: ModelCapabilities | null;
  default_params?: Record<string, any> | null;
  is_active?: boolean;
}

export interface ModelUpdateRequest {
  display_name?: string;
  description?: string | null;
  provider?: string;
  model_name?: string;
  model_type?: ModelTypeFilter;
  base_url?: string | null;
  api_key?: string | null;
  environment?: ModelEnvironment;
  visibility_scope?: ModelVisibilityScope;
  org_id?: string | null;
  dept_id?: string | null;
  public_dept_ids?: string[] | null;
  provider_config?: Record<string, any> | null;
  capabilities?: ModelCapabilities | null;
  default_params?: Record<string, any> | null;
  is_active?: boolean;
}

export interface TestConnectionRequest {
  provider: string;
  model_name: string;
  base_url?: string | null;
  api_key?: string | null;
  provider_config?: Record<string, any> | null;
}

export interface TestConnectionResponse {
  success: boolean;
  message: string;
  latency_ms?: number | null;
}
