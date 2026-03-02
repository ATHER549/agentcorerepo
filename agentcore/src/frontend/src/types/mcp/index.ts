export type MCPServerInfoType = {
  id?: string;
  name: string;
  description?: string;
  mode: string | null;
  toolsCount: number | null;
  error?: string;
};

export type MCPServerType = {
  name: string;
  command?: string;
  url?: string;
  args?: string[];
  env?: Record<string, string>;
  headers?: Record<string, string>;
};

// --- MCP Registry types (PostgreSQL-backed) ---

export interface McpRegistryType {
  id: string;
  server_name: string;
  description?: string | null;
  mode: "sse" | "stdio";
  deployment_env?: "DEV" | "UAT" | "PROD" | "dev" | "uat" | "prod";
  url?: string | null;
  command?: string | null;
  args?: string[] | null;
  has_env_vars: boolean;
  has_headers: boolean;
  is_active: boolean;
  status?: string;
  org_id?: string | null;
  dept_id?: string | null;
  visibility?: "private" | "public";
  public_scope?: "organization" | "department" | null;
  public_dept_ids?: string[];
  shared_user_ids?: string[];
  approval_status?: "pending" | "approved" | "rejected";
  requested_by?: string | null;
  request_to?: string | null;
  requested_at?: string | null;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  review_comments?: string | null;
  created_by?: string | null;
  created_by_id?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface McpRegistryCreateRequest {
  server_name: string;
  description?: string | null;
  mode: "sse" | "stdio";
  deployment_env?: "DEV" | "UAT" | "PROD" | "dev" | "uat" | "prod";
  url?: string | null;
  command?: string | null;
  args?: string[] | null;
  env_vars?: Record<string, string> | null;
  headers?: Record<string, string> | null;
  is_active?: boolean;
  status?: string;
  org_id?: string | null;
  dept_id?: string | null;
  visibility?: "private" | "public";
  public_scope?: "organization" | "department" | null;
  public_dept_ids?: string[] | null;
  shared_user_emails?: string[] | null;
  created_by?: string | null;
  created_by_id?: string | null;
}

export interface McpRegistryUpdateRequest {
  server_name?: string;
  description?: string | null;
  mode?: "sse" | "stdio";
  deployment_env?: "DEV" | "UAT" | "PROD" | "dev" | "uat" | "prod";
  url?: string | null;
  command?: string | null;
  args?: string[] | null;
  env_vars?: Record<string, string> | null;
  headers?: Record<string, string> | null;
  is_active?: boolean;
  status?: string;
  org_id?: string | null;
  dept_id?: string | null;
  visibility?: "private" | "public";
  public_scope?: "organization" | "department" | null;
  public_dept_ids?: string[] | null;
  shared_user_ids?: string[] | null;
}

export interface McpTestConnectionRequest {
  mode: "sse" | "stdio";
  url?: string | null;
  command?: string | null;
  args?: string[] | null;
  env_vars?: Record<string, string> | null;
  headers?: Record<string, string> | null;
}

export interface McpTestConnectionResponse {
  success: boolean;
  message: string;
  tools_count?: number;
}

export interface McpToolInfo {
  name: string;
  description: string;
}

export interface McpProbeResponse {
  success: boolean;
  message: string;
  tools_count?: number;
  tools?: McpToolInfo[];
}
