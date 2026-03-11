import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import Loading from "@/components/ui/loading";
import { processAgents } from "@/utils/reactFlowUtils";
import useAgentsManagerStore from "../../stores/agentsManagerStore";
import Page from "../AgentBuilderPage/components/PageComponent";

export default function ViewPage() {
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);
  const agents = useAgentsManagerStore((state) => state.agents);
  const { id } = useParams();

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!id) return;

    setIsLoading(true);
    setError(null);
    setReady(false);

    const load = async () => {
      // Fast path: agent already in store's agents list
      const fromStore = agents?.find((a) => a.id === id);
      const hasFlowData =
        !!fromStore?.data &&
        Array.isArray((fromStore.data as any).nodes) &&
        Array.isArray((fromStore.data as any).edges);
      if (fromStore && hasFlowData) {
        setCurrentAgent(fromStore);
        setReady(true);
        setIsLoading(false);
        return;
      }

      // Slow path: direct API call.
      // We intentionally avoid useGetAgent (mutation) here because its onSettled
      // triggers a full agents-list refetch which calls setAgents(), which would
      // overwrite currentAgent if the agent isn't in the user's visible list,
      // causing an infinite re-fetch loop or an eventual navigate("/all").
      try {
        const response = await api.get(`${getURL("AGENTS")}/${id}`);
        const { agents: processed } = processAgents([response.data]);
        if (processed[0]) {
          setCurrentAgent(processed[0]);
          setReady(true);
        } else {
          setError("Failed to process agent data.");
        }
      } catch (err: any) {
        const status = err?.response?.status;
        if (status === 403 || status === 404) {
          setError("Agent not found or you don't have permission to view it.");
        } else {
          setError("Failed to load agent. Please try again.");
        }
      } finally {
        setIsLoading(false);
      }
    };

    load();
  }, [id]); // Only re-run when the route id changes — NOT when agents store changes

  // Cleanup: release the store when this view unmounts
  useEffect(() => {
    return () => {
      setCurrentAgent(undefined);
    };
  }, []);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loading />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2">
        <p className="text-muted-foreground">{error}</p>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loading />
      </div>
    );
  }

  return (
    <div className="agent-page-positioning">
      <Page view setIsLoading={() => undefined} />
    </div>
  );
}
