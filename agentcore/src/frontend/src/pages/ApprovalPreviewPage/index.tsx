import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import type { AgentType } from "@/types/agent";
import { useGetTypes } from "@/controllers/API/queries/agents/use-get-types";
import { useGetApprovalPreview } from "@/controllers/API/queries/approvals";
import CustomLoader from "@/customization/components/custom-loader";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useTypesStore } from "@/stores/typesStore";
import { processAgents } from "@/utils/reactFlowUtils";
import Page from "../AgentBuilderPage/components/PageComponent";

export default function ApprovalPreviewPage(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useCustomNavigate();
  const { agentId } = useParams();
  const types = useTypesStore((state) => state.types);
  const setCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);

  useGetTypes({
    enabled: Object.keys(types).length <= 0,
  });

  const {
    data: previewData,
    isLoading,
    isError,
  } = useGetApprovalPreview(
    { agent_id: agentId || "" },
    { enabled: !!agentId },
  );

  useEffect(() => {
    const snapshot = previewData?.snapshot as any;
    const isFlowSnapshot = Array.isArray(snapshot?.nodes);
    if (previewData && isFlowSnapshot) {
      const flowAgent: AgentType = {
        id: `approval-preview-${previewData.id}`,
        name: previewData.title,
        description: "",
        data: snapshot,
        public: true,
        locked: true,
      };
      const { agents } = processAgents([flowAgent]);
      setCurrentAgent(agents[0]);
    }
    return () => {
      setCurrentAgent(undefined);
    };
  }, [previewData, setCurrentAgent]);

  const snapshot = previewData?.snapshot as any;
  const isFlowSnapshot = Array.isArray(snapshot?.nodes);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">
            {previewData?.title || t("Review Details")}
          </h1>
          <p className="text-xs text-muted-foreground">
            {isFlowSnapshot ? t("Read-only flow preview") : t("Submitted request details")}
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate("/approval")}>
          {t("Back to Approval")}
        </Button>
      </div>
      <div className="flex-1 min-h-0 w-full overflow-auto">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <CustomLoader />
          </div>
        ) : !previewData || isError ? (
          <div className="flex h-full w-full items-center justify-center p-6">
            <div className="rounded-lg border border-border bg-card p-6 text-center">
              <p className="text-sm text-muted-foreground">
                {t("Unable to load review preview for this approval.")}
              </p>
            </div>
          </div>
        ) : isFlowSnapshot ? (
          <Page
            view
            enableViewportInteractions
            setIsLoading={() => undefined}
          />
        ) : snapshot?.model_id ? (
          /* Model approval preview - simple request details */
          <div className="p-6">
            <div className="mx-auto max-w-2xl space-y-6">
              {/* Model Name & Description */}
              <div className="rounded-lg border border-border bg-card p-4">
                <h2 className="text-lg font-semibold">{snapshot.display_name}</h2>
                {snapshot.description && (
                  <p className="mt-2 text-sm text-muted-foreground">{snapshot.description}</p>
                )}
              </div>

              {/* Requested Details */}
              <div className="space-y-4 rounded-lg border border-border bg-card p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("Requested Details")}
                </h3>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Provider")}</div>
                    <div className="font-medium capitalize">{snapshot.provider}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Model ID")}</div>
                    <div className="font-mono font-medium">{snapshot.model_name}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Type")}</div>
                    <div className="font-medium uppercase">{snapshot.model_type}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Requested Environment")}</div>
                    <div className="font-medium uppercase">
                      {(() => {
                        const env = snapshot.final_target_environment || snapshot.target_environment || snapshot.environment;
                        return env === "test" ? "DEV" : env?.toUpperCase();
                      })()}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Requested Visibility")}</div>
                    <div className="font-medium capitalize">
                      {snapshot.visibility_requested || snapshot.visibility_scope}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">{t("Status")}</div>
                    <div className="font-medium capitalize">{snapshot.approval_status}</div>
                  </div>
                </div>
              </div>

              {/* Request Information (charge code, project, reason) */}
              {snapshot.provider_config?.request_meta && (
                <div className="space-y-4 rounded-lg border border-border bg-card p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    {t("Request Information")}
                  </h3>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    {snapshot.provider_config.request_meta.charge_code && (
                      <div>
                        <div className="text-xs text-muted-foreground">{t("Charge Code")}</div>
                        <div className="font-medium">{snapshot.provider_config.request_meta.charge_code}</div>
                      </div>
                    )}
                    {snapshot.provider_config.request_meta.project_name && (
                      <div>
                        <div className="text-xs text-muted-foreground">{t("Project Name")}</div>
                        <div className="font-medium">{snapshot.provider_config.request_meta.project_name}</div>
                      </div>
                    )}
                  </div>
                  {snapshot.provider_config.request_meta.reason && (
                    <div>
                      <div className="text-xs text-muted-foreground">{t("Reason")}</div>
                      <div className="mt-1 text-sm">{snapshot.provider_config.request_meta.reason}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ) : (
          /* Generic fallback for MCP and other non-flow snapshots */
          <div className="p-6">
            <div className="rounded-lg border border-border bg-card p-4">
              <pre className="whitespace-pre-wrap break-words text-sm text-foreground">
                {JSON.stringify(previewData.snapshot, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
