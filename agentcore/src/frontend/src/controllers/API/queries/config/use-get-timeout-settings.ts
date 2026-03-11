import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";

export interface TimeoutSetting {
  id: string;
  label: string;
  value: string;
  unit: string;
  units: string[];
  description: string;
  type: "input" | "switch";
  checked?: boolean;
}

export const useGetTimeoutSettings = () =>
  useQuery<TimeoutSetting[]>({
    queryKey: ["timeout-settings"],
    queryFn: async () => {
      const response = await api.get(`${getURL("TIMEOUT_SETTINGS")}/`);
      return response.data ?? [];
    },
    refetchOnWindowFocus: false,
  });
