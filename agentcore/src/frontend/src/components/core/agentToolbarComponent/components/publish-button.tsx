import ForwardedIconComponent from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { PUBLISH_BUTTON_NAME } from "@/constants/constants";
import { ENABLE_PUBLISH } from "@/customization/feature-flags";
import { AuthContext } from "@/contexts/authContext";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import useAgentStore from "@/stores/agentStore";
import useAlertStore from "@/stores/alertStore";
import { useNameAvailability } from "@/controllers/API/queries/common/use-name-availability";
import { useGetPublishStatus } from "@/controllers/API/queries/agents/use-get-publish-status";
import { useValidatePublishEmail } from "@/controllers/API/queries/agents/use-validate-publish-email";
import { usePatchUpdateAgent } from "@/controllers/API/queries/agents/use-patch-update-agent";
import { usePostUnifiedPublishAgent } from "@/controllers/API/queries/agents/use-post-unified-publish-agent";
import { cn } from "@/utils/utils";
import { Input } from "@/components/ui/input";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";

interface PublishButtonProps {
  hasIO: boolean;
}

interface PublishContextResponse {
  department_id: string;
  department_admin_id: string;
}

interface PublishContextResolveResult {
  data: PublishContextResponse | null;
  errorDetail?: string;
}

const PublishIcon = () => (
  <ForwardedIconComponent
    name="Upload"
    className="h-4 w-4 transition-all"
    strokeWidth={ENABLE_PUBLISH ? 2 : 1.5}
  />
);

const ButtonLabel = () => (
  <span className="hidden md:block">{PUBLISH_BUTTON_NAME}</span>
);

const ActiveButton = ({ onClick }: { onClick: () => void }) => (
  <button
    type="button"
    onClick={onClick}
    data-testid="playground-btn-agent-io"
    className="playground-btn-agent-toolbar cursor-pointer hover:bg-accent"
  >
    <PublishIcon />
    <ButtonLabel />
  </button>
);

const DisabledButton = () => (
  <div
    className="playground-btn-agent-toolbar cursor-not-allowed text-muted-foreground duration-150"
    data-testid="playground-btn-agent"
  >
    <PublishIcon />
    <ButtonLabel />
  </div>
);

const PublishButton = ({
  hasIO,
}: PublishButtonProps) => {
  const { permissions, userData } = useContext(AuthContext);
  const navigate = useCustomNavigate();
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const canPublish = can("view_project_page");
  const currentAgent = useAgentsManagerStore((state) => state.currentAgent);
  const agents = useAgentsManagerStore((state) => state.agents);
  const setAgents = useAgentsManagerStore((state) => state.setAgents);
  const setManagerCurrentAgent = useAgentsManagerStore((state) => state.setCurrentAgent);
  const setCanvasCurrentAgent = useAgentStore((state) => state.setCurrentAgent);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const validatePublishEmail = useValidatePublishEmail();
  const { mutateAsync: mutateUpdateAgent } = usePatchUpdateAgent();

  const [open, setOpen] = useState(false);
  const [agentNameInput, setAgentNameInput] = useState("");
  const [publishUat, setPublishUat] = useState(false);
  const [publishProd, setPublishProd] = useState(false);
  const [prodPublic, setProdPublic] = useState(false);
  const [prodPrivate, setProdPrivate] = useState(false);
  const [publishDescription, setPublishDescription] = useState("");
  const [emailsInput, setEmailsInput] = useState("");
  const [emailValidationResults, setEmailValidationResults] = useState<
    Array<{ email: string; department_id: string | null; exists_in_department: boolean; message: string }>
  >([]);
  const [validationInProgress, setValidationInProgress] = useState(false);
  const latestValidationRun = useRef(0);
  const publishMutation = usePostUnifiedPublishAgent();
  const { data: publishStatus } = useGetPublishStatus(
    { agent_id: currentAgent?.id ?? "" },
    { refetchInterval: 30000 },
  );
  const hasPendingApproval = Boolean(publishStatus?.has_pending_approval);
  const agentNameAvailability = useNameAvailability({
    entity: "agent",
    name: agentNameInput,
    exclude_id: currentAgent?.id ?? null,
    enabled: open && agentNameInput.trim().length > 0,
  });

  const normalizedEmails = useMemo(() => {
    return Array.from(
      new Set(
        emailsInput
          .split(/[\n,;\s]+/)
          .map((email) => email.trim().toLowerCase())
          .filter(Boolean),
      ),
    );
  }, [emailsInput]);

  const invalidEmails = useMemo(() => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return normalizedEmails.filter((email) => !emailRegex.test(email));
  }, [normalizedEmails]);

  useEffect(() => {
    if (open) {
      setAgentNameInput(currentAgent?.name ?? "");
    }
  }, [open, currentAgent?.name]);

  const validateEmails = async () => {
    if (!currentAgent?.id) {
      setErrorData({ title: "No active agent found." });
      return null;
    }
    if (invalidEmails.length > 0) {
      setErrorData({
        title: "Invalid email format",
        list: invalidEmails,
      });
      return null;
    }

    setValidationInProgress(true);
    const runId = ++latestValidationRun.current;
    try {
      const responses = await Promise.all(
        normalizedEmails.map((email) =>
          validatePublishEmail.mutateAsync({
            agent_id: currentAgent.id,
            email,
          }),
        ),
      );
      if (runId !== latestValidationRun.current) {
        return null;
      }
      setEmailValidationResults(responses);
      return responses;
    } catch (error: any) {
      if (runId !== latestValidationRun.current) {
        return null;
      }
      setErrorData({
        title: "Email validation failed",
        list: [error?.response?.data?.detail ?? "Please try again."],
      });
      return null;
    } finally {
      if (runId === latestValidationRun.current) {
        setValidationInProgress(false);
      }
    }
  };

  const resolvePublishContext = async (
    suppressError = false,
  ): Promise<PublishContextResolveResult> => {
    if (!currentAgent?.id) {
      const detail = "No active agent found.";
      if (!suppressError) {
        setErrorData({ title: detail });
      }
      return { data: null, errorDetail: detail };
    }
    try {
      const response = await api.get<PublishContextResponse>(
        `${getURL("PUBLISH")}/${currentAgent.id}/context`,
      );
      return { data: response.data };
    } catch (error: any) {
      const detail = error?.response?.data?.detail ?? "Please try again.";
      if (!suppressError) {
        setErrorData({
          title: "Unable to resolve publish context.",
          list: [detail],
        });
      }
      return { data: null, errorDetail: detail };
    }
  };

  const resolveDepartmentFromCurrentUserEmail = async (): Promise<string | null> => {
    if (!currentAgent?.id) {
      return null;
    }

    const fallbackEmail = (userData?.username ?? "").trim().toLowerCase();
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!fallbackEmail || !emailRegex.test(fallbackEmail)) {
      return null;
    }

    try {
      const selfValidation = await validatePublishEmail.mutateAsync({
        agent_id: currentAgent.id,
        email: fallbackEmail,
      });
      return selfValidation.department_id;
    } catch {
      return null;
    }
  };

  useEffect(() => {
    if (!open) return;
    if (!currentAgent?.id) return;

    if (normalizedEmails.length === 0) {
      setEmailValidationResults([]);
      setValidationInProgress(false);
      return;
    }

    if (invalidEmails.length > 0) {
      setEmailValidationResults([]);
      setValidationInProgress(false);
      return;
    }

    const timer = setTimeout(() => {
      void validateEmails();
    }, 450);

    return () => clearTimeout(timer);
  }, [emailsInput, open, currentAgent?.id]);

  const handleSubmit = async () => {
    if (!currentAgent?.id) {
      setErrorData({ title: "No active agent found." });
      return;
    }
    if (hasPendingApproval) {
      setErrorData({
        title: "Awaiting approval",
        list: ["This agent already has a pending PROD approval request."],
      });
      return;
    }
    if (agentNameAvailability.isNameTaken) {
      setErrorData({
        title: "Agent name already taken",
        list: [agentNameAvailability.reason || "Please choose a different name."],
      });
      return;
    }
    const trimmedName = agentNameInput.trim();
    if (!trimmedName) {
      setErrorData({ title: "Agent name cannot be empty." });
      return;
    }

    if (trimmedName !== (currentAgent?.name ?? "")) {
      try {
        const updatedAgent = await mutateUpdateAgent({
          id: currentAgent.id,
          name: trimmedName,
        });

        if (agents) {
          setAgents(
            agents.map((agent) => (agent.id === updatedAgent.id ? updatedAgent : agent)),
          );
        }
        setManagerCurrentAgent(updatedAgent);
        setCanvasCurrentAgent(updatedAgent);
      } catch (error: any) {
        setErrorData({
          title: "Failed to update agent name",
          list: [error?.response?.data?.detail ?? "Please try again."],
        });
        return;
      }
    }

    if (!publishUat && !publishProd) {
      setErrorData({
        title: "Select at least one publishing environment (UAT or PROD).",
      });
      return;
    }
    if (publishProd && !prodPublic && !prodPrivate) {
      setErrorData({
        title: "For PROD, select public or private.",
      });
      return;
    }

    let resolvedDepartmentId: string | null = null;
    let resolvedDepartmentAdminId = userData?.department_admin ?? undefined;

    if (normalizedEmails.length > 0) {
      const results = await validateEmails();
      if (!results) {
        return;
      }

      const missingEmails = results
        .filter((item) => !item.exists_in_department)
        .map((item) => item.email);

      if (missingEmails.length > 0) {
        setErrorData({
          title: "Some emails are not available in this department.",
          list: missingEmails,
        });
        return;
      }

      resolvedDepartmentId =
        results.find((item) => item.exists_in_department && item.department_id)?.department_id ??
        results.find((item) => item.department_id)?.department_id ??
        null;
    } else {
      const contextResult = await resolvePublishContext(true);
      if (contextResult.data) {
        resolvedDepartmentId = contextResult.data.department_id;
        resolvedDepartmentAdminId =
          contextResult.data.department_admin_id ?? resolvedDepartmentAdminId;
      } else {
        const fallbackDepartmentId = await resolveDepartmentFromCurrentUserEmail();
        if (!fallbackDepartmentId) {
          setErrorData({
            title: "Unable to resolve publish context.",
            list: [contextResult.errorDetail ?? "Please provide at least one valid email ID."],
          });
          return;
        }
        resolvedDepartmentId = fallbackDepartmentId;
      }
    }

    if (!resolvedDepartmentId) {
      setErrorData({
        title: "Unable to resolve department_id for publish payload.",
      });
      return;
    }

    const publishRequests: Array<{
      environment: "uat" | "prod";
      visibility: "PUBLIC" | "PRIVATE";
    }> = [];
    if (publishUat) {
      publishRequests.push({ environment: "uat", visibility: "PRIVATE" });
    }
    if (publishProd) {
      publishRequests.push({
        environment: "prod",
        visibility: prodPublic ? "PUBLIC" : "PRIVATE",
      });
    }

    try {
      const responses: Array<{
        environment: "uat" | "prod";
        message: string;
        version_number: string;
      }> = [];
      for (const request of publishRequests) {
        const response = await publishMutation.mutateAsync({
          agent_id: currentAgent.id,
          department_id: resolvedDepartmentId,
          ...(resolvedDepartmentAdminId
            ? { department_admin_id: resolvedDepartmentAdminId }
            : {}),
          environment: request.environment,
          visibility: request.visibility,
          publish_description: publishDescription.trim() || undefined,
        });
        responses.push(response);
      }

      const responseLines = responses.map(
        (response) =>
          `${response.environment.toUpperCase()}: ${response.message} (${response.version_number})`,
      );
      setSuccessData({
        title: `Publish completed successfully. ${responseLines.join(" | ")}`,
      });
      setOpen(false);
      if (publishProd) {
        const folderId =
          (currentAgent as any)?.project_id ||
          (currentAgent as any)?.folder_id ||
          "";
        navigate(folderId ? `/agents/folder/${folderId}` : "/agents");
      }
    } catch (error: any) {
      setErrorData({
        title: "Failed to publish agent",
        list: [error?.response?.data?.detail ?? "Please try again."],
      });
      return;
    }

  };

  // If user doesn't have edit_agents permission, show disabled button with no interaction
  if (!canPublish) {
    return (
      <ShadTooltip content="You don't have permission to publish">
        <div className="pointer-events-none">
          <DisabledButton />
        </div>
      </ShadTooltip>
    );
  }

  // If user has permission but agent doesn't have IO, show disabled with different tooltip
  if (!hasIO) {
    return (
      <ShadTooltip content="Add a Chat Input or Chat Output to use the playground">
        <div className="pointer-events-none">
          <DisabledButton />
        </div>
      </ShadTooltip>
    );
  }

  if (hasPendingApproval) {
    return (
      <ShadTooltip content="This agent is awaiting approval. You can publish again after approve/reject.">
        <div className="pointer-events-none">
          <DisabledButton />
        </div>
      </ShadTooltip>
    );
  }

  // User has permission and agent has IO - show active button
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <ActiveButton onClick={() => setOpen(true)} />
      <DialogContent
        className={cn(
          "left-auto right-4 top-1/2 h-auto max-h-[88dvh] w-[min(32rem,calc(100vw-2rem))] translate-x-0 -translate-y-1/2 rounded-xl border p-0 shadow-2xl",
          "data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right",
          "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-100",
        )}
      >
        <DialogHeader className="space-y-2 border-b bg-gradient-to-r from-slate-50 to-white px-6 py-5">
          <DialogTitle className="text-base">Publish Agent</DialogTitle>
          <div className="rounded-md border bg-white p-3 text-sm">
            <Label htmlFor="publish-agent-name" className="text-xs text-muted-foreground">
              Agent name
            </Label>
            <Input
              id="publish-agent-name"
              value={agentNameInput}
              onChange={(event) => setAgentNameInput(event.target.value)}
              placeholder="Enter agent name"
              className="mt-2"
            />
            {agentNameInput.trim().length > 0 &&
              !agentNameAvailability.isFetching &&
              agentNameAvailability.isNameTaken && (
                <p className="mt-2 text-xs font-medium text-red-500">
                  {agentNameAvailability.reason ?? "This agent name is already taken."}
                </p>
              )}
          </div>
        </DialogHeader>

        <div className="flex max-h-[calc(88dvh-96px)] flex-col gap-5 overflow-y-auto px-6 py-5">
          <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
            <Label className="text-sm font-medium">Publishing Environment</Label>
            <div className="flex items-center gap-2">
              <Checkbox
                id="publish-uat"
                checked={publishUat}
                onCheckedChange={(checked) => setPublishUat(checked === true)}
              />
              <Label htmlFor="publish-uat">UAT</Label>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="publish-prod"
                checked={publishProd}
                onCheckedChange={(checked) => {
                  const enabled = checked === true;
                  setPublishProd(enabled);
                  if (!enabled) {
                    setProdPublic(false);
                    setProdPrivate(false);
                  }
                }}
              />
              <Label htmlFor="publish-prod">PROD</Label>
            </div>

            {publishProd && (
              <div className="mt-2 space-y-2 rounded-md border bg-background p-3">
                <Label className="text-sm font-medium">PROD visibility</Label>
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="prod-public"
                    checked={prodPublic}
                    onCheckedChange={(checked) => {
                      const enabled = checked === true;
                      setProdPublic(enabled);
                      if (enabled) setProdPrivate(false);
                    }}
                  />
                  <Label htmlFor="prod-public">Public</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="prod-private"
                    checked={prodPrivate}
                    onCheckedChange={(checked) => {
                      const enabled = checked === true;
                      setProdPrivate(enabled);
                      if (enabled) setProdPublic(false);
                    }}
                  />
                  <Label htmlFor="prod-private">Private</Label>
                </div>
              </div>
            )}
          </div>

          <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
            <Label htmlFor="publish-description" className="text-sm font-medium">
              Publish description (optional)
            </Label>
            <Textarea
              id="publish-description"
              value={publishDescription}
              onChange={(event) => setPublishDescription(event.target.value)}
              placeholder="What changed in this release?"
              className="min-h-[72px] bg-background"
            />
          </div>

          <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
            <Label htmlFor="publish-emails" className="text-sm font-medium">
              Business/User Email IDs (optional)
            </Label>
            <Textarea
              id="publish-emails"
              value={emailsInput}
              onChange={(event) => setEmailsInput(event.target.value)}
              placeholder="Enter one or multiple emails (comma, space, or newline separated)"
              className="min-h-[120px] bg-background"
            />
            <span className="text-xs text-muted-foreground">
              Validation runs automatically while typing and is restricted to this agent's department.
            </span>
            {validationInProgress && (
              <div className="text-xs text-muted-foreground">Checking emails...</div>
            )}

            {emailValidationResults.length > 0 && (
              <div className="rounded-md border bg-background p-3">
                <div className="mb-2 text-xs font-medium text-muted-foreground">
                  Validation result
                </div>
                <div className="space-y-1 text-sm">
                  {emailValidationResults.map((result) => (
                    <div key={result.email} className="flex items-center justify-between gap-3">
                      <span className="truncate">{result.email}</span>
                      <span
                        className={cn(
                          "text-xs font-medium",
                          result.exists_in_department ? "text-green-600" : "text-red-600",
                        )}
                      >
                        {result.exists_in_department ? "Available" : "Not in department"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="mt-auto flex items-center justify-end gap-2 border-t pt-4">
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={
                validationInProgress ||
                publishMutation.isPending ||
                agentNameAvailability.isFetching ||
                agentNameAvailability.isNameTaken
              }
            >
              {publishMutation.isPending ? "Publishing..." : "Submit Publish Request"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default PublishButton;
