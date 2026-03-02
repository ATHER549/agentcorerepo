import { cloneDeep } from "lodash";
import { useRef } from "react";
import buildQueryStringUrl from "@/controllers/utils/create-query-param-string";
import type { PaginatedFolderType } from "@/pages/MainPage/entities";
import { useFolderStore } from "@/stores/foldersStore";
import type { useQueryFunctionType } from "@/types/api";
import { processAgents } from "@/utils/reactFlowUtils";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IGetFolder {
  id: string;
  page?: number;
  size?: number;
  is_component?: boolean;
  is_agent?: boolean;
  search?: string;
}

const addQueryParams = (url: string, params: IGetFolder): string => {
  return buildQueryStringUrl(url, params);
};

export const useGetFolderQuery: useQueryFunctionType<
  IGetFolder,
  PaginatedFolderType | undefined
> = (params, options) => {
  const { query } = UseRequestProcessor();

  const folders = useFolderStore((state) => state.folders);
  const latestIdRef = useRef("");

  const getFolderFn = async (
    params: IGetFolder,
  ): Promise<PaginatedFolderType | undefined> => {
    if (params.id) {
      if (latestIdRef.current !== params.id) {
        params.page = 1;
      }
      latestIdRef.current = params.id;

      const existingFolder = folders.find((f) => f.id === params.id);
      if (!existingFolder) {
        return;
      }
    }

    const url = addQueryParams(`${getURL("PROJECTS")}/${params.id}`, params);
    const { data } = await api.get<PaginatedFolderType>(url);

    const { agents } = processAgents(data.agents.items);

    const dataProcessed = cloneDeep(data);
    dataProcessed.agents.items = agents;

    return dataProcessed;
  };

  const queryResult = query(
    [
      "useGetFolder",
      params.id,
      {
        page: params.page,
        size: params.size,
        is_component: params.is_component,
        is_agent: params.is_agent,
        search: params.search,
      },
    ],
    () => getFolderFn(params),
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
