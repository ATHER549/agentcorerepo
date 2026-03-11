import { BASE_URL_API, BASE_URL_API_V2 } from "../../../constants/constants";

export const URLs = {
  TRANSACTIONS: `monitor/transactions`,
  API_KEY: `api_key`,
  FILES: `files`,
  FILE_MANAGEMENT: `files`,
  VERSION: `version`,
  MESSAGES: `monitor/messages`,
  BUILDS: `monitor/builds`,
  STORE: `store`,
  USERS: "users",
  LOGOUT: `logout`,
  LOGIN: `login`,
  REFRESH: "refresh",
  BUILD: `build`,
  CUSTOM_COMPONENT: `custom_component`,
  AGENTS: `agents`,
  FOLDERS: `projects`,
  PROJECTS: `projects`,
  VARIABLES: `variables`,
  VALIDATE: `validate`,
  CONFIG: `config`,
  STARTER_PROJECTS: `starter-projects`,
  SIDEBAR_CATEGORIES: `sidebar_categories`,
  ALL: `all`,
  VOICE: `voice`,
  PUBLIC_FLOW: `agents/public_agent`,
  MCP: `mcp/project`,
  MCP_SERVERS: `mcp/servers`,
  KNOWLEDGE_BASES: `knowledge_bases`,
  MODELS: `models`,
  REGISTRY: `registry`,
  VECTOR_DB_CATALOGUE: `vector-db-catalogue`,
  GUARDRAILS_CATALOGUE: `guardrails-catalogue`,
  TIMEOUT_SETTINGS: `timeout-settings`,
  APPROVALS: `approvals`,
  CONTROL_PANEL: `control-panel`,
  PUBLISH: `publish`,
  ROLES: `roles`,
  HELP_SUPPORT: `help-support`,
  ORCHESTRATOR: `orchestrator`,
  PACKAGES: `packages`,
  RELEASES: `releases`,
  CONNECTOR_CATALOGUE: `connector-catalogue`,
  TRIGGERS: `triggers`,
  TEAMS: `teams`,
  HITL: `v1/hitl`,
} as const;

// IMPORTANT: FOLDERS endpoint now points to 'projects' for backward compatibility

export function getURL(
  key: keyof typeof URLs,
  params: any = {},
  v2: boolean = false,
) {
  let url = URLs[key];
  for (const paramKey of Object.keys(params)) {
    url += `/${params[paramKey]}`;
  }
  return `${v2 ? BASE_URL_API_V2 : BASE_URL_API}${url}`;
}

export type URLsType = typeof URLs;
