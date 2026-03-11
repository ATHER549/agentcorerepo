import { useContext, useEffect, useState } from "react";
import { useBlocker, useParams, useSearchParams } from "react-router-dom";
import SideBarFoldersButtonsComponent from "@/components/core/folderSidebarComponent/components/sideBarFolderButtons";
import { Button } from "@/components/ui/button";
import { SidebarProvider } from "@/components/ui/sidebar";
import { useGetAgent } from "@/controllers/API/queries/agents/use-get-agent";
import { useGetTypes } from "@/controllers/API/queries/agents/use-get-types";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
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
import { useTranslation } from "react-i18next";
import { AuthContext } from "@/contexts/authContext";
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
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const [isLoading, setIsLoading] = useState(false);

  const isBuilding = useAgentStore((state) => state.isBuilding);
  const setOnAgentBuilderPage = useAgentStore((state) => state.setOnAgentBuilderPage);
  const stopBuilding = useAgentStore((state) => state.stopBuilding);
  const { id, folderId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useCustomNavigate();
  const saveAgent = useSaveAgent();
  const { userData, role } = useContext(AuthContext);
  const currentUserId = String(userData?.id ?? "");
  const normalizedRole = String(role ?? "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  const isAdminRole = ["root", "super_admin", "department_admin", "admin", "root_admin"].includes(
    normalizedRole,
  );
  const requestedReadOnlyMode = view || searchParams.get("readonly") === "1";
  const forceReadOnlyByOwnership =
    !!folderId &&
    isAdminRole &&
    !!currentAgent &&
    (!!currentAgent.user_id ? String(currentAgent.user_id) !== currentUserId : true);
  const isReadOnlyMode = requestedReadOnlyMode || forceReadOnlyByOwnership;

  const changesNotSaved =
    !isReadOnlyMode &&
    customStringify(currentAgent) !== customStringify(currentSavedAgent) &&
    (currentAgent?.data?.nodes?.length ?? 0) > 0;

  const blocker = useBlocker(!isReadOnlyMode && (changesNotSaved || isBuilding));

  const currentAgentId = useAgentsManagerStore((state) => state.currentAgentId);
  const updatedAt = currentSavedAgent?.updated_at;
  const autoSaving = useAgentsManagerStore((state) => state.autoSaving);
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
    if (isReadOnlyMode) return;
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
  }, [changesNotSaved, isBuilding, isReadOnlyMode]);

  const getAgentToAddToCanvas = async (agentId: string) => {
    try {
      const agent = await getAgent({ id: agentId });
      const shouldForceReadOnlyForFetchedAgent =
        !!folderId &&
        isAdminRole &&
        (!!agent?.user_id ? String(agent.user_id) !== currentUserId : true);
      if (!requestedReadOnlyMode && !shouldForceReadOnlyForFetchedAgent) {
        await api.post(`${getURL("AGENTS")}/${agentId}/session/acquire`);
      }
      setCurrentAgent(agent);
    } catch (error: any) {
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;
      setErrorData({
        title: status === 423 ? "Agent is currently locked" : "Unable to open agent",
        list: [typeof detail === "string" ? detail : "Please try again later."],
      });
      navigate("/all");
    }
  };

  // Set agent tab id
  useEffect(() => {
    const awaitGetTypes = async () => {
      if (!id || Object.keys(types).length === 0) {
        return;
      }

      // Route id is the source of truth. If store has stale state, reload.
      if (currentAgentId !== id || !currentAgent) {
        await getAgentToAddToCanvas(id);
      }
    };
    awaitGetTypes();
  }, [id, currentAgentId, currentAgent, types, isReadOnlyMode]);

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
      !isReadOnlyMode &&
      blocker.state === "blocked" &&
      autoSaving &&
      changesNotSaved &&
      !isBuilding
    ) {
      handleSave();
    }
  }, [blocker.state, isBuilding, autoSaving, changesNotSaved, isReadOnlyMode]);

  useEffect(() => {
    if (!isReadOnlyMode && blocker.state === "blocked") {
      if (isBuilding) {
        stopBuilding();
      } else if (!changesNotSaved) {
        blocker.proceed && blocker.proceed();
      }
    }
  }, [blocker.state, isBuilding, stopBuilding, changesNotSaved, isReadOnlyMode]);

  useEffect(() => {
    if (!id || !currentAgent || isReadOnlyMode) return;

    const heartbeat = setInterval(() => {
      api.post(`${getURL("AGENTS")}/${id}/session/acquire`).catch(() => {
        // Keep UX non-disruptive; hard failures are handled on explicit open.
      });
    }, 60_000);

    const release = () => {
      api.post(`${getURL("AGENTS")}/${id}/session/release`).catch(() => {
        // Best-effort release.
      });
    };

    window.addEventListener("beforeunload", release);

    return () => {
      clearInterval(heartbeat);
      window.removeEventListener("beforeunload", release);
      release();
    };
  }, [id, currentAgent, isReadOnlyMode]);

  const isMobile = useIsMobile();
  const handleBackToProject = () => {
    if (folderId) {
      navigate(`/agents/folder/${folderId}`);
      return;
    }
    navigate("/agents");
  };

  return (
    <>
      <div className="agent-page-positioning">
        {currentAgent && (
          <div className="flex h-full overflow-hidden">
            {isReadOnlyMode ? (
              <SidebarProvider width="280px">
                <SideBarFoldersButtonsComponent
                  handleChangeFolder={(projectId: string) =>
                    navigate(`/agents/folder/${projectId}`)
                  }
                  handleFilesClick={() => navigate("/assets/files")}
                />
                <main className="flex h-full w-full overflow-hidden">
                  <div className="flex h-full w-full flex-col overflow-hidden">
                    <div className="flex items-center gap-2 border-b bg-background px-3 py-2">
                      <Button variant="outline" size="sm" onClick={handleBackToProject}>
                        Back to Project
                      </Button>
                      <span className="truncate text-sm text-muted-foreground">
                        {currentAgent.name}
                      </span>
                    </div>
                    <div className="h-full w-full">
                      <Page
                        view
                        enableViewportInteractions
                        setIsLoading={setIsLoading}
                      />
                    </div>
                  </div>
                </main>
              </SidebarProvider>
            ) : (
              <SidebarProvider
                width="17.5rem"
                defaultOpen={!isMobile}
                segmentedSidebar={ENABLE_NEW_SIDEBAR}
              >
                <AgentSearchProvider>
                  <AgentSidebarComponent isLoading={isLoading} />
                  <main className="flex w-full overflow-hidden">
                    <div className="h-full w-full">
                      <Page setIsLoading={setIsLoading} />
                    </div>
                  </main>
                </AgentSearchProvider>
              </SidebarProvider>
            )}
          </div>
        )}
      </div>
      {!isReadOnlyMode && blocker.state === "blocked" && (
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
