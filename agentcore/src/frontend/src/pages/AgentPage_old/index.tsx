import { useEffect, useState } from "react";
import { useBlocker, useParams } from "react-router-dom";
import { SidebarProvider } from "@/components/ui/sidebar";
import { useGetAgent } from "@/controllers/API/queries/agents/use-get-agent";
import { useGetTypes } from "@/controllers/API/queries/agents/use-get-types";
import { ENABLE_NEW_SIDEBAR } from "@/customization/feature-flags";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useSaveAgent from "@/hooks/agents/use-save-agent";
import { useIsMobile } from "@/hooks/use-mobile";
import { SaveChangesModal } from "@/modals/saveChangesModal";
import useAlertStore from "@/stores/alertStore";
import { useTypesStore } from "@/stores/typesStore";
import { customStringify } from "@/utils/reactFlowUtils";
import useAgentStore from "../../stores/agentStore";
import useAgentsManagerStore from "../../stores/agentsManagerStore";
import { useTranslation } from 'react-i18next';
import {
  AgentSearchProvider,
  AgentSidebarComponent,
} from "./components/agentSidebarComponent";
import Page from "./components/PageComponent";

export default function AgentBuilderPage({ view }: { view?: boolean }): JSX.Element {
  const types = useTypesStore((state) => state.types);

  useGetTypes({
    enabled: Object.keys(types).length <= 0,
  });
  const { t } = useTranslation();
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);
  const currentAgent = useAgentStore((state) => state.currentAgent);
  const currentSavedAgent = useAgentsManagerStore((state) => state.currentAgent);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const [isLoading, setIsLoading] = useState(false);

  const changesNotSaved =
    customStringify(currentAgent) !== customStringify(currentSavedAgent) &&
    (currentAgent?.data?.nodes?.length ?? 0) > 0;

  const isBuilding = useAgentStore((state) => state.isBuilding);
  const blocker = useBlocker(changesNotSaved || isBuilding);

  const setOnAgentBuilderPage = useAgentStore((state) => state.setOnAgentBuilderPage);
  const { id } = useParams();
  const navigate = useCustomNavigate();
  const saveAgent = useSaveAgent();

  const currentAgentId = useAgentsManagerStore((state) => state.currentAgentId);

  const updatedAt = currentSavedAgent?.updated_at;
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
  const stopBuilding = useAgentStore((state) => state.stopBuilding);

  const { mutateAsync: getAgent } = useGetAgent();

  const handleSave = () => {
    let saving = true;
    let proceed = false;
    setTimeout(() => {
      saving = false;
      if (proceed) {
        blocker.proceed && blocker.proceed();
        setSuccessData({
          title: t("Agent saved successfully!"),
        });
      }
    }, 1200);
    saveAgent().then(() => {
      if (!autoSaving || saving === false) {
        blocker.proceed && blocker.proceed();
        setSuccessData({
          title: t("Agent saved successfully!"),
        });
      }
      proceed = true;
    });
  };

  const handleExit = () => {
    if (isBuilding) {
      // Do nothing, let the blocker handle it
    } else if (changesNotSaved) {
      if (blocker.proceed) blocker.proceed();
    } else {
      navigate("/all");
    }
  };

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (changesNotSaved || isBuilding) {
        event.preventDefault();
        event.returnValue = ""; // Required for Chrome
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [changesNotSaved, isBuilding]);

  // Set agent tab id
  useEffect(() => {
    const awaitgetTypes = async () => {
      if (!id || Object.keys(types).length === 0) {
        return;
      }

      // Keep route id as source of truth. Without this, a stale currentAgentId
      // can block loading when opening an agent URL directly.
      if (currentAgentId !== id || !currentAgent) {
        await getAgentToAddToCanvas(id);
      }
    };
    awaitgetTypes();
  }, [id, currentAgentId, currentAgent, types]);

  useEffect(() => {
    setOnAgentBuilderPage(true);

    return () => {
      setOnAgentBuilderPage(false);
      console.warn("unmounting");

      setCurrentAgent(undefined);
    };
  }, [id]);

  useEffect(() => {
    if (
      blocker.state === "blocked" &&
      autoSaving &&
      changesNotSaved &&
      !isBuilding
    ) {
      handleSave();
    }
  }, [blocker.state, isBuilding]);

  useEffect(() => {
    if (blocker.state === "blocked") {
      if (isBuilding) {
        stopBuilding();
      } else if (!changesNotSaved) {
        blocker.proceed && blocker.proceed();
      }
    }
  }, [blocker.state, isBuilding]);

  const getAgentToAddToCanvas = async (id: string) => {
    const agent = await getAgent({ id: id });
    setCurrentAgent(agent);
  };

  const isMobile = useIsMobile();

  return (
    <>
      <div className="agent-page-positioning">
        {currentAgent && (
          <div className="flex h-full overflow-hidden">
            <SidebarProvider
              width="17.5rem"
              defaultOpen={!isMobile}
              segmentedSidebar={ENABLE_NEW_SIDEBAR}
            >
              <AgentSearchProvider>
                {!view && <AgentSidebarComponent isLoading={isLoading} />}
                <main className="flex w-full overflow-hidden">
                  <div className="h-full w-full">
                    <Page setIsLoading={setIsLoading} />
                  </div>
                </main>
              </AgentSearchProvider>
            </SidebarProvider>
          </div>
        )}
      </div>
      {blocker.state === "blocked" && (
        <>
          {!isBuilding && currentSavedAgent && (
            <SaveChangesModal
              onSave={handleSave}
              onCancel={() => blocker.reset?.()}
              onProceed={handleExit}
              agentName={t(currentSavedAgent.name)}
              lastSaved={
                updatedAt
                  ? new Date(updatedAt).toLocaleString("en-US", {
                      hour: "numeric",
                      minute: "numeric",
                      second: "numeric",
                      month: "numeric",
                      day: "numeric",
                    })
                  : undefined
              }
              autoSave={autoSaving}
            />
          )}
        </>
      )}
    </>
  );
}
