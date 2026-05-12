import { Bot, Eye, Shield } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import Loading from "@/components/ui/loading";
import type { GuardrailInfo } from "@/controllers/API/queries/guardrails";
import {
  type GuardrailVersion,
  useGetGuardrailVersions,
} from "@/controllers/API/queries/guardrails";
import { useGetGuardrailVersionAgents } from "@/controllers/API/queries/guardrails";

interface GuardrailVersionHistoryProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  guardrail: GuardrailInfo | null;
}

export default function GuardrailVersionHistory({
  open,
  onOpenChange,
  guardrail,
}: GuardrailVersionHistoryProps): JSX.Element {
  const { t } = useTranslation();
  const [selectedVersion, setSelectedVersion] =
    useState<GuardrailVersion | null>(null);

  const { data, isLoading } = useGetGuardrailVersions(
    { guardrailId: guardrail?.id ?? "" },
    { enabled: open && !!guardrail?.id },
  );

  const { data: agentData, isLoading: agentsLoading } =
    useGetGuardrailVersionAgents(
      { guardrailId: guardrail?.id ?? "" },
      { enabled: open && !!guardrail?.id },
    );

  const versions = data?.versions ?? [];
  const versionAgents = agentData?.version_agents ?? {};

  const handleViewSnapshot = (version: GuardrailVersion) => {
    setSelectedVersion(version);
  };

  const handleCloseSnapshot = () => {
    setSelectedVersion(null);
  };

  return (
    <>
      <Dialog open={open && !selectedVersion} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5" />
              {t("Version History")}
              {guardrail && (
                <span className="text-sm font-normal text-muted-foreground">
                  — {guardrail.name}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>

          <div className="max-h-[400px] overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loading />
              </div>
            ) : versions.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                {t("No versions found.")}
              </div>
            ) : (
              <div className="space-y-3">
                {versions.map((version) => {
                  const agents = versionAgents[version.id] ?? [];
                  return (
                    <div
                      key={version.id}
                      className="rounded-lg border border-border p-3"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold">
                              v{version.version_number}
                            </span>
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {new Date(version.created_at).toLocaleString()}
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleViewSnapshot(version)}
                        >
                          <Eye className="mr-1 h-4 w-4" />
                          {t("View")}
                        </Button>
                      </div>

                      {/* Agent usage section */}
                      <div className="mt-2 border-t border-border/50 pt-2">
                        {agentsLoading ? (
                          <div className="text-xs text-muted-foreground">
                            {t("Loading agent usage...")}
                          </div>
                        ) : agents.length > 0 ? (
                          <div className="flex flex-wrap items-center gap-1.5">
                            <Bot className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            <span className="text-xs font-medium text-muted-foreground">
                              {t("Used by")}:
                            </span>
                            {agents.map((agent, idx) => (
                              <span
                                key={`${agent.agent_id}-${idx}`}
                                className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                                title={`Deployed ${agent.deployed_at ? new Date(agent.deployed_at).toLocaleString() : "N/A"}`}
                              >
                                {agent.agent_name}
                                <span className="ml-1 text-[10px] opacity-70">
                                  ({agent.deployment_version})
                                </span>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground/60">
                            <Bot className="h-3.5 w-3.5 shrink-0" />
                            {t("No agents currently using this version")}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Snapshot viewer dialog */}
      <Dialog
        open={!!selectedVersion}
        onOpenChange={(open) => {
          if (!open) handleCloseSnapshot();
        }}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {t("Version")} v{selectedVersion?.version_number} —{" "}
              {selectedVersion?.guardrail_name}
            </DialogTitle>
          </DialogHeader>

          {selectedVersion && (
            <div className="max-h-[500px] space-y-4 overflow-y-auto">
              <div className="text-sm">
                <span className="font-medium text-muted-foreground">
                  {t("Created")}:
                </span>{" "}
                {new Date(selectedVersion.created_at).toLocaleString()}
              </div>

              {selectedVersion.guardrail_snapshot?.runtime_config && (
                <div>
                  <h4 className="mb-2 text-sm font-medium">
                    {t("Runtime Configuration")}
                  </h4>
                  {selectedVersion.guardrail_snapshot.runtime_config
                    .config_yml && (
                    <div className="mb-3">
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        config.yml
                      </label>
                      <pre className="max-h-[200px] overflow-auto rounded-md border bg-muted/50 p-3 text-xs">
                        {
                          selectedVersion.guardrail_snapshot.runtime_config
                            .config_yml
                        }
                      </pre>
                    </div>
                  )}
                  {selectedVersion.guardrail_snapshot.runtime_config
                    .rails_co && (
                    <div className="mb-3">
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        rails.co
                      </label>
                      <pre className="max-h-[200px] overflow-auto rounded-md border bg-muted/50 p-3 text-xs">
                        {
                          selectedVersion.guardrail_snapshot.runtime_config
                            .rails_co
                        }
                      </pre>
                    </div>
                  )}
                  {selectedVersion.guardrail_snapshot.runtime_config
                    .prompts_yml && (
                    <div className="mb-3">
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        prompts.yml
                      </label>
                      <pre className="max-h-[200px] overflow-auto rounded-md border bg-muted/50 p-3 text-xs">
                        {
                          selectedVersion.guardrail_snapshot.runtime_config
                            .prompts_yml
                        }
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
