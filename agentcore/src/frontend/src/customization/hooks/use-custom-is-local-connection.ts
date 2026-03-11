import { useMemo } from "react";

/**
 * Hook to check if the current window is being accessed through a local connection
 * @returns A boolean indicating if the current connection is local
 */
export function useCustomIsLocalConnection(): boolean {
  return useMemo(() => {
    // Get the current window's hostname
    const currentHostname = window.location.hostname;

    // List of hostnames/IPs that are considered local
    const localHost =
      process.env.HOST_IP ||
      process.env.LOCALHOST_HOST ||
      window.location.hostname;
    const localAddresses = [localHost, "127.0.0.1", "0.0.0.0"];

    // Check if the current hostname is in the local addresses list
    return localAddresses.includes(currentHostname);
  }, []);
}
