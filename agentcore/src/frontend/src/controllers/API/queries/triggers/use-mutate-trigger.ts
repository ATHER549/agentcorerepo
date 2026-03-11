import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import type { TriggerInfo } from "./use-get-all-triggers";

export interface CreateTriggerPayload {
  trigger_type: "schedule" | "folder_monitor" | "email_monitor";
  trigger_config: Record<string, any>;
  environment: string;
  version?: string | null;
  deployment_id?: string | null;
}

export const useCreateTrigger = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      agentId,
      payload,
    }: {
      agentId: string;
      payload: CreateTriggerPayload;
    }) => {
      const res = await api.post(
        `${getURL("TRIGGERS")}/${agentId}`,
        payload,
      );
      return res.data as TriggerInfo;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetAllTriggers"] });
    },
  });
};

export const useUpdateTrigger = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      triggerId,
      payload,
    }: {
      triggerId: string;
      payload: { trigger_config?: Record<string, any>; is_active?: boolean; environment?: string; version?: string };
    }) => {
      const res = await api.patch(
        `${getURL("TRIGGERS")}/${triggerId}`,
        payload,
      );
      return res.data as TriggerInfo;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetAllTriggers"] });
    },
  });
};

export const useToggleTrigger = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (triggerId: string) => {
      const res = await api.post(
        `${getURL("TRIGGERS")}/${triggerId}/toggle`,
      );
      return res.data as TriggerInfo;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetAllTriggers"] });
    },
  });
};

export const useDeleteTrigger = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (triggerId: string) => {
      await api.delete(`${getURL("TRIGGERS")}/${triggerId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetAllTriggers"] });
    },
  });
};

export const useRunTriggerNow = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (triggerId: string) => {
      const res = await api.post(
        `${getURL("TRIGGERS")}/${triggerId}/run-now`,
      );
      return res.data as { message: string };
    },
    onSuccess: (_, triggerId) => {
      queryClient.invalidateQueries({ queryKey: ["useGetAllTriggers"] });
      // Give the background task ~600 ms to write "started" to DB,
      // then pull fresh logs so the slide-over shows "Running..."
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["useGetTriggerLogs", triggerId] });
      }, 600);
    },
  });
};

export interface TriggerExecutionLog {
  id: string;
  trigger_config_id: string;
  agent_id: string;
  status: "started" | "success" | "error";
  error_message: string | null;
  execution_duration_ms: number | null;
  triggered_at: string;
  payload: Record<string, any> | null;
}

export const useGetTriggerLogs = (triggerId: string, limit = 50) => {
  return useQuery({
    queryKey: ["useGetTriggerLogs", triggerId],
    queryFn: async (): Promise<TriggerExecutionLog[]> => {
      const res = await api.get(
        `${getURL("TRIGGERS")}/${triggerId}/logs?limit=${limit}`,
      );
      return res.data ?? [];
    },
    enabled: Boolean(triggerId),
    staleTime: 0,                  // always treat data as stale → refetch on mount
    refetchOnMount: "always",      // force fresh fetch every time slide-over opens
    refetchOnWindowFocus: false,
    refetchInterval: 2_000,        // poll every 2 s so Running → Success flip is visible
  });
};
