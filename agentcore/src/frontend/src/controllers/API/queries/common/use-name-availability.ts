import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";

type NameEntity = "agent" | "mcp" | "connector" | "guardrail";

interface NameAvailabilityRequest {
  entity: NameEntity;
  name: string;
  org_id?: string | null;
  dept_id?: string | null;
  exclude_id?: string | null;
}

interface NameAvailabilityResponse {
  available: boolean;
  reason?: string | null;
}

interface UseNameAvailabilityParams extends NameAvailabilityRequest {
  enabled?: boolean;
  debounceMs?: number;
}

export function useNameAvailability(params: UseNameAvailabilityParams) {
  const {
    entity,
    name,
    org_id,
    dept_id,
    exclude_id,
    enabled = true,
    debounceMs = 350,
  } = params;

  const [debouncedName, setDebouncedName] = useState(name);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedName(name), debounceMs);
    return () => clearTimeout(timer);
  }, [name, debounceMs]);

  const trimmedName = debouncedName.trim();
  const isEnabled = enabled && trimmedName.length > 0;

  const query = useQuery<NameAvailabilityResponse>({
    queryKey: [
      "name-availability",
      entity,
      trimmedName.toLowerCase(),
      org_id ?? null,
      dept_id ?? null,
      exclude_id ?? null,
    ],
    enabled: isEnabled,
    queryFn: async () => {
      const response = await api.post(`${getURL("VALIDATE")}/name`, {
        entity,
        name: trimmedName,
        org_id: org_id || null,
        dept_id: dept_id || null,
        exclude_id: exclude_id || null,
      });
      return response.data as NameAvailabilityResponse;
    },
    staleTime: 10_000,
  });

  return {
    ...query,
    checkedName: trimmedName,
    isNameTaken:
      isEnabled && !query.isFetching && query.data?.available === false,
    reason: query.data?.reason ?? null,
  };
}

