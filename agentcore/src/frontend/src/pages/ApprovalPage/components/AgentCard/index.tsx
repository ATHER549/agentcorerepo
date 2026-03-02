import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle, FileCode2 } from "lucide-react";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { useTranslation } from "react-i18next";

interface AgentCardProps {
  id: string;
  entityType?: "agent" | "model" | "mcp";
  title: string;
  status: "pending" | "approved" | "rejected";
  description: string;
  submittedBy: {
    name: string;
    avatar?: string;
  };
  project: string;
  submitted: string;
  version: string;
  recentChanges: string;
  onReject: () => void;
  onApprove: () => void;
  onReviewDetails: () => void;
  onViewMcpConfig?: () => void;
}

const ENTITY_BADGE_CLASSES: Record<string, string> = {
  model: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  mcp: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

const ENTITY_LABELS: Record<string, string> = {
  model: "Model",
  mcp: "MCP",
};

export function AgentCard({
  entityType = "agent",
  title,
  status,
  description,
  submittedBy,
  project,
  submitted,
  version,
  recentChanges,
  onReject,
  onApprove,
  onReviewDetails,
  onViewMcpConfig,
}: AgentCardProps) {
  const { t } = useTranslation();

  const statusColors = {
    pending:
      "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
    approved:
      "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    rejected: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  };

  const { permissions, role } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const submittedDisplay = (() => {
    const dt = new Date(submitted);
    if (Number.isNaN(dt.getTime())) return submitted;
    return dt.toLocaleString();
  })();
  const submittedByDisplay = (() => {
    const raw = submittedBy?.name?.trim() ?? "";
    if (!raw) return t("Unknown");
    const atIndex = raw.indexOf("@");
    return atIndex > 0 ? raw.slice(0, atIndex) : raw;
  })();

  return (
    <div className="rounded-lg border border-border bg-card p-6 transition-shadow hover:shadow-md">
      {/* Header */}
      <div className="mb-4 flex items-start justify-between">
        <div className="flex-1">
          <div className="mb-2 flex items-center gap-3">
            <h3 className="text-lg font-semibold">{title}</h3>
            {entityType && entityType !== "agent" && (
              <span
                className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  ENTITY_BADGE_CLASSES[entityType] ?? ""
                }`}
              >
                {t(ENTITY_LABELS[entityType] ?? entityType)}
              </span>
            )}
            <span
              className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${statusColors[status]}`}
            >
              {t(status.charAt(0).toUpperCase() + status.slice(1))}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </div>

      {/* Metadata */}
      <div className="mb-4 grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground">{t("Submitted By")}</div>
          <div className="truncate font-medium" title={submittedByDisplay}>
            {submittedByDisplay}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">{t("Project")}</div>
          <div className="font-medium">{project}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">{t("Version")}</div>
          <div className="font-medium">{version || "-"}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">{t("Submitted")}</div>
          <div className="font-medium">{submittedDisplay}</div>
        </div>
      </div>

      {/* Recent Changes - hidden for models */}
      {entityType !== "model" && (
        <div className="mb-4 rounded-md bg-muted/50 p-3">
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {t("Recent Changes")}
          </div>
          <div className="text-sm font-medium">{recentChanges}</div>
        </div>
      )}

      {/* Actions */}
      {/* Actions */}
      <div className="flex w-full items-center gap-2">
        {/* LEFT actions */}
        <div className="flex flex-wrap items-center gap-2">
          {entityType === "mcp" ? (
            <Button variant="outline" onClick={onViewMcpConfig} className="gap-2">
              <FileCode2 className="h-4 w-4" />
              {t("MCP Config")}
            </Button>
          ) : (
            <Button variant="outline" onClick={onReviewDetails} className="gap-2">
              <FileCode2 className="h-4 w-4" />
              {t("Review Details")}
            </Button>
          )}
        </div>

        {/* RIGHT actions */}
        {status === "pending" && (
          <div className="ml-auto flex items-center gap-2">
           <ShadTooltip 
  content={!can("prod_publish_approval_required") ? t("You don't have permission to reject") : ""}
>
  <span className="inline-block">
    <Button
      variant="outline"
      onClick={onReject}
      disabled={!can("prod_publish_approval_required")}
      className="
        gap-2
        border-red-500 text-red-600
        hover:!bg-red-50 hover:!text-red-600
        dark:border-red-700 dark:text-red-400
        dark:hover:!bg-red-950/30 dark:hover:!text-red-400
      "
    >
      <XCircle className="h-4 w-4" />
      {t("Reject")}
    </Button>
  </span>
</ShadTooltip>
           
          <ShadTooltip 
  content={!can("prod_publish_approval_required") ? t("You don't have permission to approve") : ""}
>
            <Button
              variant="outline"
              onClick={onApprove}
              className="
    gap-2
    !border-green-700 text-green-600
    hover:!border-green-700 focus-visible:!border-green-700
    disabled:!border-green-700 disabled:!opacity-100
    hover:!bg-green-50 hover:!text-green-600
    dark:border-green-700 dark:text-green-400
    dark:hover:!border-green-700 dark:focus-visible:!border-green-700
    dark:disabled:!border-green-700
    dark:hover:!bg-green-950/30 dark:hover:!text-green-400
  "
  disabled={!can("prod_publish_approval_required")}
            >
              <CheckCircle2 className="h-4 w-4" />
              {t("Approve")}
            </Button>
          </ShadTooltip>
          </div>
        )}
      </div>
    </div>
  );
}
