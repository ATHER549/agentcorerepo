// Types for Microsoft Teams integration

export interface TeamsPublishRequest {
  agent_id: string;
  display_name?: string;
  short_description?: string;
  long_description?: string;
  bot_app_id?: string;
  bot_app_secret?: string;
}

export interface TeamsPublishResponse {
  teams_app_id: string;
  agent_id: string;
  status: TeamsPublishStatus;
  teams_external_id?: string;
  message: string;
}

export interface TeamsAppStatusResponse {
  agent_id: string;
  status: TeamsPublishStatus;
  teams_external_id?: string;
  display_name: string;
  published_at?: string;
  last_error?: string;
  has_own_bot?: boolean;
  bot_app_id?: string;
}

export type TeamsPublishStatus =
  | "DRAFT"
  | "UPLOADED"
  | "PUBLISHED"
  | "FAILED"
  | "UNPUBLISHED";

export interface TeamsHealthResponse {
  configured: boolean;
  bot_app_id: string;
  endpoint_base: string;
  adapter?: string;
  graph_api?: string;
}

export interface TeamsOAuthStatusResponse {
  connected: boolean;
}
