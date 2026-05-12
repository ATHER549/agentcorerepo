import { Eye, Shield } from "lucide-react";
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

  const versions = data?.versions ?? [];

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
                {versions.map((version) => (
                  <div
                    key={version.id}
                    className="flex items-center justify-between rounded-lg border border-border p-3"
                  >
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
                ))}
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
