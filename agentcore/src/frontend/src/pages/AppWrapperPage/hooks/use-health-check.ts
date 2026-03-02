import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { useEffect, useState } from "react";
import { useGetHealthQuery } from "@/controllers/API/queries/health";
import useAgentStore from "@/stores/agentStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useUtilityStore } from "@/stores/utilityStore";

export function useHealthCheck() {
  const healthCheckMaxRetries = useAgentsManagerStore(
    (state) => state.healthCheckMaxRetries,
  );

  const healthCheckTimeout = useUtilityStore(
    (state) => state.healthCheckTimeout,
  );

  const isMutating = useIsMutating();
  const isFetching = useIsFetching({
    predicate: (query) => query.queryKey[0] !== "useGetHealthQuery",
  });
  const isBuilding = useAgentStore((state) => state.isBuilding);

  const disabled = isMutating || isFetching || isBuilding;

  const {
    isFetching: fetchingHealth,
    isError: isErrorHealth,
    error,
    refetch,
  } = useGetHealthQuery({ enableInterval: !disabled });
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const isServerBusy =
      (error as AxiosError)?.response?.status === 503 ||
      (error as AxiosError)?.response?.status === 429;

    if (isServerBusy && isErrorHealth && !disabled) {
      const maxRetries = healthCheckMaxRetries;
      if (retryCount < maxRetries) {
        const delay = 2 ** retryCount * 1000;
        const timer = setTimeout(() => {
          refetch();
          setRetryCount(retryCount + 1);
        }, delay);

        return () => clearTimeout(timer);
      }
    } else {
      setRetryCount(0);
    }
  }, [isErrorHealth, retryCount, refetch]);

  return { healthCheckTimeout, refetch, fetchingHealth };
}
