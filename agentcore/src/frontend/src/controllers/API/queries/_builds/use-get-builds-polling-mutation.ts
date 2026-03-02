import { useEffect, useRef } from "react";
import useAlertStore from "@/stores/alertStore";
import useAgentStore from "@/stores/agentStore";
import { useUtilityStore } from "@/stores/utilityStore";
import type { useMutationFunctionType } from "@/types/api";
import type { AgentPoolType } from "@/types/zustand/agent";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

const _ERROR_DISPLAY_INTERVAL = 10000;
const _ERROR_DISPLAY_COUNT = 1;

interface PollingItem {
  interval: NodeJS.Timeout;
  timestamp: number;
  agentId: string;
  callback: () => Promise<void>;
}

const PollingManager = {
  pollingQueue: new Map<string, PollingItem[]>(),
  activePolls: new Map<string, PollingItem>(),

  enqueuePolling(agentId: string, pollingItem: PollingItem) {
    if (!this.pollingQueue.has(agentId)) {
      this.pollingQueue.set(agentId, []);
    }
    this.pollingQueue.set(
      agentId,
      (this.pollingQueue.get(agentId) || []).filter(
        (item) => item.timestamp !== pollingItem.timestamp,
      ),
    );
    this.pollingQueue.get(agentId)?.push(pollingItem);

    if (!this.activePolls.has(agentId)) {
      this.startNextPolling(agentId);
    }
  },

  startNextPolling(agentId: string) {
    const queue = this.pollingQueue.get(agentId) || [];
    if (queue.length === 0) {
      this.activePolls.delete(agentId);
      return;
    }

    const nextPoll = queue[0];
    this.activePolls.set(agentId, nextPoll);
    nextPoll.callback();
  },

  stopPoll(agentId: string) {
    const activePoll = this.activePolls.get(agentId);
    if (activePoll) {
      clearInterval(activePoll.interval);
      this.activePolls.delete(agentId);
      const queue = this.pollingQueue.get(agentId) || [];
      this.pollingQueue.set(
        agentId,
        queue.filter((item) => item.timestamp !== activePoll.timestamp),
      );
      this.startNextPolling(agentId);
    }
  },

  stopAll() {
    this.activePolls.forEach((poll) => clearInterval(poll.interval));
    this.activePolls.clear();
    this.pollingQueue.clear();
  },

  removeFromQueue(agentId: string, timestamp: number) {
    const queue = this.pollingQueue.get(agentId) || [];
    this.pollingQueue.set(
      agentId,
      queue.filter((item) => item.timestamp !== timestamp),
    );
  },
};

interface IGetBuilds {
  agentId: string;
  onSuccess?: (data: { vertex_builds: AgentPoolType }) => void;
  stopPollingOn?: (data: { vertex_builds: AgentPoolType }) => boolean;
}

export const useGetBuildsMutation: useMutationFunctionType<
  undefined,
  IGetBuilds
> = (options?) => {
  const { mutate } = UseRequestProcessor();
  const webhookPollingInterval = useUtilityStore(
    (state) => state.webhookPollingInterval,
  );

  const setAgentPool = useAgentStore((state) => state.setAgentPool);
  const currentAgent = useAgentStore((state) => state.currentAgent);

  const agentIdRef = useRef<string | null>(null);
  const requestInProgressRef = useRef<Record<string, boolean>>({});
  const errorDisplayCountRef = useRef<number>(0);
  const timeoutIdsRef = useRef<number[]>([]);

  const setErrorData = useAlertStore((state) => state.setErrorData);

  const getBuildsFn = async (
    payload: IGetBuilds,
  ): Promise<{ vertex_builds: AgentPoolType } | undefined> => {
    if (requestInProgressRef.current[payload.agentId]) {
      return Promise.reject("Request already in progress");
    }

    try {
      requestInProgressRef.current[payload.agentId] = true;
      const config = {};
      config["params"] = { agent_id: payload.agentId };
      const res = await api.get<any>(`${getURL("BUILDS")}`, config);

      if (currentAgent) {
        const agentPool = res?.data?.vertex_builds;
        if (Object.keys(agentPool).length > 0) {
          setAgentPool(agentPool);
        }

        // Check for errors only if we haven't displayed them yet
        if (errorDisplayCountRef.current === 0) {
          Object.keys(agentPool).forEach((key) => {
            const nodeBuild = agentPool[key];
            if (nodeBuild.length > 0 && nodeBuild[0]?.valid === false) {
              const errorMessage = nodeBuild?.[0]?.params || "Unknown error";
              if (errorMessage) {
                setErrorData({
                  title: "Last build failed",
                  list: [errorMessage],
                });
                errorDisplayCountRef.current = 1;
              }
            }
          });
        }

        return;
      }

      return res.data;
    } finally {
      requestInProgressRef.current[payload.agentId] = false;
    }
  };

  const startPolling = (payload: IGetBuilds) => {
    if (requestInProgressRef.current[payload.agentId]) {
      return Promise.reject("Request already in progress");
    }

    if (!webhookPollingInterval || webhookPollingInterval === 0) {
      return getBuildsFn(payload);
    }

    if (
      agentIdRef.current === payload.agentId &&
      PollingManager.activePolls.has(payload.agentId)
    ) {
      return Promise.resolve({ vertex_builds: {} as AgentPoolType });
    }

    agentIdRef.current = payload.agentId;

    const timestamp = Date.now();
    const pollCallback = async () => {
      const data = await getBuildsFn(payload);
      payload.onSuccess?.(data!);

      if (payload.stopPollingOn?.(data!)) {
        PollingManager.stopPoll(payload.agentId);
      }
    };

    const intervalId = setInterval(pollCallback, webhookPollingInterval);

    const pollingItem: PollingItem = {
      interval: intervalId,
      timestamp,
      agentId: payload.agentId,
      callback: pollCallback,
    };

    PollingManager.enqueuePolling(payload.agentId, pollingItem);

    return getBuildsFn(payload).then((data) => {
      payload.onSuccess?.(data!);
      if (payload.stopPollingOn?.(data!)) {
        PollingManager.stopPoll(payload.agentId);
      }
    });
  };

  useEffect(() => {
    return () => {
      if (agentIdRef.current) {
        PollingManager.stopPoll(agentIdRef.current);
      }
      // Clear all timeouts
      timeoutIdsRef.current.forEach((timeoutId) => {
        clearTimeout(timeoutId);
      });
      timeoutIdsRef.current = [];
      // Reset error display count when component unmounts
      errorDisplayCountRef.current = 0;
    };
  }, []);

  const mutation = mutate(
    ["useGetBuildsMutation"],
    (payload: IGetBuilds) =>
      startPolling(payload) ?? Promise.reject("Failed to start polling"),
    {
      ...options,
      retry: 0,
      retryDelay: 0,
    },
  );

  return mutation;
};

export { PollingManager };
