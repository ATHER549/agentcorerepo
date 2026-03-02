import { useContext } from "react";
import IconComponent from "@/components/common/genericIconComponent";
import ShadTooltipComponent from "@/components/common/shadTooltipComponent";
import { Badge } from "@/components/ui/badge";
import { useGetPublishStatus } from "@/controllers/API/queries/agents/use-get-publish-status";
import { AuthContext } from "@/contexts/authContext";
import useAgentsManagerStore from "@/stores/agentsManagerStore";

export default function PublishStatusBadge() {
  const currentAgent = useAgentsManagerStore((state) => state.currentAgent);
  const agentId = currentAgent?.id;
  const { userData } = useContext(AuthContext);
  const currentUserId = String(userData?.id ?? "");

  const { data: publishStatus } = useGetPublishStatus(
    { agent_id: agentId ?? "" },
    { refetchInterval: 30000 },
  );

  if (!publishStatus) {
    return null;
  }

  const isRequester =
    (publishStatus.pending_requested_by &&
      String(publishStatus.pending_requested_by) === currentUserId) ||
    (publishStatus.latest_prod_published_by &&
      String(publishStatus.latest_prod_published_by) === currentUserId);

  if (!isRequester) {
    return null;
  }

  const latestDecision = (publishStatus.latest_review_decision || "").toUpperCase();
  const latestProdStatus = (publishStatus.latest_prod_status || "").toUpperCase();
  const activeProdStatus = (publishStatus.prod?.status || "").toUpperCase();

  if (publishStatus.has_pending_approval) {
    return (
      <ShadTooltipComponent side="bottom" content="Your PROD publish request is awaiting admin approval.">
        <Badge
          variant="outline"
          className="flex items-center gap-1 border-amber-500 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:bg-amber-950 dark:text-amber-300"
        >
          <IconComponent name="Clock3" className="h-3 w-3" />
          <span className="text-xs">Awaiting Approval</span>
        </Badge>
      </ShadTooltipComponent>
    );
  }

  if (latestDecision === "REJECTED") {
    return (
      <ShadTooltipComponent side="bottom" content="Your last PROD publish request was rejected.">
        <Badge
          variant="outline"
          className="flex items-center gap-1 border-red-500 bg-red-50 text-red-700 hover:bg-red-100 dark:bg-red-950 dark:text-red-300"
        >
          <IconComponent name="XCircle" className="h-3 w-3" />
          <span className="text-xs">Rejected</span>
        </Badge>
      </ShadTooltipComponent>
    );
  }

  if (latestProdStatus === "PUBLISHED" || activeProdStatus === "PUBLISHED") {
    return (
      <ShadTooltipComponent side="bottom" content="Your PROD publish request is approved and deployed.">
        <Badge
          variant="outline"
          className="flex items-center gap-1 border-green-500 bg-green-50 text-green-700 hover:bg-green-100 dark:bg-green-950 dark:text-green-300"
        >
          <IconComponent name="CheckCircle2" className="h-3 w-3" />
          <span className="text-xs">Approved</span>
        </Badge>
      </ShadTooltipComponent>
    );
  }

  return null;
}

