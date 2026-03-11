import type { AgentType } from "../../../types/agent";

export type FolderType = {
  name: string;
  description: string;
  id?: string | null;
  parent_id: string;
  created_at?: string;
  updated_at?: string;
  is_own_project?: boolean;
  created_by_email?: string | null;
  department_name?: string | null;
  organization_name?: string | null;
  agents: AgentType[];
  components: string[];
};

export type PaginatedFolderType = {
  project: {
    name: string;
    description: string;
    id?: string | null;
    parent_id: string;
    components: string[];
  };
  agents: {
    items: AgentType[];
    total: number;
    page: number;
    size: number;
    pages: number;
  };
};

export type AddFolderType = {
  name: string;
  description: string;
  id?: string | null;
  parent_id: string | null;
  agents?: string[];
  components?: string[];
};

export type StarterProjectsType = {
  name?: string;
  description?: string;
  agents?: AgentType[];
  id: string;
  parent_id: string;
};
