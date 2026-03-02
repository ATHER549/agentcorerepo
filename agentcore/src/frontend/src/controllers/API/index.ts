import type { Edge, Node, reactFlowJsonObject } from "@xyflow/react";
import type { AxiosRequestConfig, AxiosResponse } from "axios";
import {
  customGetAppVersions,
  customGetLatestVersion,
} from "@/customization/utils/custom-get-app-latest-version";
import { BASE_URL_API } from "../../constants/constants";
import { api } from "../../controllers/API/api";
import type {
  VertexBuildTypeAPI,
  VerticesOrderTypeAPI,
} from "../../types/api/index";
import type { AgentStyleType, AgentType } from "../../types/agent";
import type { StoreComponentResponse } from "../../types/store";

const GITHUB_API_URL = "https://api.github.com";
const DISCORD_API_URL =
  "https://discord.com/api/v9/invites/EqksyE2EX9?with_counts=true";

export async function getRepoStars(owner: string, repo: string) {
  try {
    const response = await api.get(`${GITHUB_API_URL}/repos/${owner}/${repo}`, {
      withCredentials: false,
    });
    return response?.data.stargazers_count;
  } catch (error) {
    // A private/moved/mistyped repo returns 404 from GitHub API.
    // Keep UI stable without noisy console errors.
    if ((error as any)?.response?.status !== 404) {
      console.error("Error fetching repository data:", error);
    }
    return null;
  }
}

export async function getDiscordCount() {
  try {
    const response = await api.get(DISCORD_API_URL, {
      withCredentials: false,
    });
    return response?.data.approximate_member_count;
  } catch (error) {
    console.error("Error fetching repository data:", error);
    return null;
  }
}

export const getAppVersions = customGetAppVersions;
export const getLatestVersion = customGetLatestVersion;

export async function createApiKey(name: string) {
  try {
    const res = await api.post(`${BASE_URL_API}api_key/`, { name });
    if (res.status === 200) {
      return res.data;
    }
  } catch (error) {
    throw error;
  }
}

/**
 * Saves a new agent to the database.
 *
 * @param {AgentType} newAgent - The agent data to save.
 * @returns {Promise<any>} The saved agent data.
 * @throws Will throw an error if saving fails.
 */
export async function saveAgentStore(
  newAgent: {
    name?: string;
    data: reactFlowJsonObject | null;
    description?: string;
    style?: AgentStyleType;
    is_component?: boolean;
    parent?: string;
    last_tested_version?: string;
  },
  tags: string[],
  publicAgent = false,
): Promise<AgentType> {
  try {
    const response = await api.post(`${BASE_URL_API}store/components/`, {
      name: newAgent.name,
      data: newAgent.data,
      description: newAgent.description,
      is_component: newAgent.is_component,
      parent: newAgent.parent,
      tags: tags,
      private: !publicAgent,
      status: publicAgent ? "Public" : "Private",
      last_tested_version: newAgent.last_tested_version,
    });

    if (response.status !== 201) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response?.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

export async function getStoreComponents({
  component_id = null,
  page = 1,
  limit = 9999999,
  is_component = null,
  sort = "-count(liked_by)",
  tags = [],
  liked = null,
  isPrivate = null,
  search = null,
  filterByUser = null,
  fields = null,
}: {
  component_id?: string | null;
  page?: number;
  limit?: number;
  is_component?: boolean | null;
  sort?: string;
  tags?: string[] | null;
  liked?: boolean | null;
  isPrivate?: boolean | null;
  search?: string | null;
  filterByUser?: boolean | null;
  fields?: Array<string> | null;
}): Promise<StoreComponentResponse | undefined> {
  try {
    let url = `${BASE_URL_API}store/components/`;
    const queryParams: any = [];
    if (component_id !== undefined && component_id !== null) {
      queryParams.push(`component_id=${component_id}`);
    }
    if (search !== undefined && search !== null) {
      queryParams.push(`search=${search}`);
    }
    if (isPrivate !== undefined && isPrivate !== null) {
      queryParams.push(`private=${isPrivate}`);
    }
    if (tags !== undefined && tags !== null && tags.length > 0) {
      queryParams.push(`tags=${tags.join(encodeURIComponent(","))}`);
    }
    if (fields !== undefined && fields !== null && fields.length > 0) {
      queryParams.push(`fields=${fields.join(encodeURIComponent(","))}`);
    }

    if (sort !== undefined && sort !== null) {
      queryParams.push(`sort=${sort}`);
    } else {
      queryParams.push(`sort=-count(liked_by)`); // default sort
    }

    if (liked !== undefined && liked !== null) {
      queryParams.push(`liked=${liked}`);
    }

    if (filterByUser !== undefined && filterByUser !== null) {
      queryParams.push(`filter_by_user=${filterByUser}`);
    }

    if (page !== undefined) {
      queryParams.push(`page=${page ?? 1}`);
    }
    if (limit !== undefined) {
      queryParams.push(`limit=${limit ?? 9999999}`);
    }
    if (is_component !== null && is_component !== undefined) {
      queryParams.push(`is_component=${is_component}`);
    }
    if (queryParams.length > 0) {
      url += `?${queryParams.join("&")}`;
    }

    const res = await api.get(url);

    if (res.status === 200) {
      return res.data;
    }
  } catch (error) {
    throw error;
  }
}

export async function getComponent(component_id: string) {
  try {
    const res = await api.get(
      `${BASE_URL_API}store/components/${component_id}`,
    );
    if (res.status === 200) {
      return res.data;
    }
  } catch (error) {
    throw error;
  }
}

export async function checkHasApiKey() {
  try {
    const res = await api.get(`${BASE_URL_API}store/check/api_key`);
    if (res?.status === 200) {
      return res.data;
    }
  } catch (error) {
    throw error;
  }
}

export async function checkHasStore() {
  try {
    const res = await api.get(`${BASE_URL_API}store/check/`);
    if (res?.status === 200) {
      return res.data;
    }
  } catch (error) {
    throw error;
  }
}

/**
 * Updates an existing agent in the Store.
 *
 * @param {AgentType} updatedAgent - The updated agent data.
 * @returns {Promise<any>} The updated agent data.
 * @throws Will throw an error if the update fails.
 */
export async function updateAgentStore(
  newAgent: {
    name?: string;
    data: reactFlowJsonObject | null;
    description?: string;
    style?: AgentStyleType;
    is_component?: boolean;
    parent?: string;
    last_tested_version?: string;
  },
  tags: string[],
  publicAgent = false,
  id: string,
): Promise<AgentType> {
  try {
    const response = await api.patch(`${BASE_URL_API}store/components/${id}`, {
      name: newAgent.name,
      data: newAgent.data,
      description: newAgent.description,
      is_component: newAgent.is_component,
      parent: newAgent.parent,
      tags: tags,
      private: !publicAgent,
      last_tested_version: newAgent.last_tested_version,
    });

    if (response.status !== 201) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response?.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

export async function getVerticesOrder(
  agentId: string,
  startNodeId?: string | null,
  stopNodeId?: string | null,
  nodes?: Node[],
  Edges?: Edge[],
): Promise<AxiosResponse<VerticesOrderTypeAPI>> {
  // nodeId is optional and is a query parameter
  // if nodeId is not provided, the API will return all vertices
  const config: AxiosRequestConfig<any> = {};
  if (stopNodeId) {
    config["params"] = { stop_component_id: stopNodeId };
  } else if (startNodeId) {
    config["params"] = { start_component_id: startNodeId };
  }
  const data = {
    data: {},
  };
  if (nodes && Edges) {
    data["data"]["nodes"] = nodes;
    data["data"]["edges"] = Edges;
  }
  return await api.post(
    `${BASE_URL_API}build/${agentId}/vertices`,
    data,
    config,
  );
}

export async function postBuildVertex(
  agentId: string,
  vertexId: string,
  input_value: string,
  files?: string[],
): Promise<AxiosResponse<VertexBuildTypeAPI>> {
  // input_value is optional and is a query parameter
  const data = {};
  if (typeof input_value !== "undefined") {
    data["inputs"] = { input_value: input_value };
  }
  if (data && files) {
    data["files"] = files;
  }
  return await api.post(
    `${BASE_URL_API}build/${agentId}/vertices/${vertexId}`,
    data,
  );
}
