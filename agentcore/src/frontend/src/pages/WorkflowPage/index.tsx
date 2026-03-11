import { ArrowUpToLine, Info, Search, Share2 } from "lucide-react";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useGetPublishEmailSuggestions } from "@/controllers/API/queries/agents/use-get-publish-email-suggestions";
import { useValidatePublishEmail } from "@/controllers/API/queries/agents/use-validate-publish-email";
import {
  useGetControlPanelAgentSharing,
  useGetControlPanelAgents,
  usePostControlPanelPromote,
  useToggleControlPanelAgent,
} from "@/controllers/API/queries/control-panel";
import CustomLoader from "@/customization/components/custom-loader";
import EmbedModal from "@/modals/EmbedModal/embed-modal";
import ExportModal from "@/modals/exportModal";
import useAlertStore from "@/stores/alertStore";
import type { AgentType } from "@/types/agent";

type EnvironmentTab = "UAT" | "PROD";

interface WorkagentType {
  id: string;
  agentId?: string;
  name: string;
  description: string;
  user: string;
  userEmail?: string;
  owner?: string;
  ownerCount?: number;
  ownerNames?: string[];
  ownerEmails?: string[];
  department: string;
  created: string;
  movedToProd?: boolean;
  status: boolean;
  enabled: boolean;
}

interface WorkflowsViewProps {
  workflows?: WorkagentType[];
  setSearch?: (search: string) => void;
  onWorkagentClick?: (workflow: WorkagentType) => void;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

export default function WorkflowsView({
  workflows = [],
  setSearch,
  onWorkagentClick,
}: WorkflowsViewProps): JSX.Element {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<EnvironmentTab>("UAT");
  const [workflowStates, setWorkagentStates] = useState<{
    [key: string]: { status: boolean; enabled: boolean };
  }>({});
  const [pendingToggles, setPendingToggles] = useState<{
    [key: string]: { status: boolean; enabled: boolean };
  }>({});
  const [selectedSharingAgentId, setSelectedSharingAgentId] =
    useState<string>("");
  const [selectedSharingAgentName, setSelectedSharingAgentName] =
    useState<string>("");
  const [promotingById, setPromotingById] = useState<Record<string, boolean>>(
    {},
  );
  const [promoteDialogOpen, setPromoteDialogOpen] = useState(false);
  const [selectedPromoteDeployId, setSelectedPromoteDeployId] =
    useState<string>("");
  const [selectedPromoteAgentId, setSelectedPromoteAgentId] =
    useState<string>("");
  const [selectedPromoteVisibility, setSelectedPromoteVisibility] = useState<
    "PRIVATE" | "PUBLIC"
  >("PRIVATE");
  const [promoteSelectedEmails, setPromoteSelectedEmails] = useState<string[]>(
    [],
  );
  const [promoteEmailDraft, setPromoteEmailDraft] = useState("");
  const [debouncedPromoteEmailQuery, setDebouncedPromoteEmailQuery] =
    useState("");
  const [promoteRecipientsInitialized, setPromoteRecipientsInitialized] =
    useState(false);
  const [openExportModal, setOpenExportModal] = useState(false);
  const [openEmbedModal, setOpenEmbedModal] = useState(false);
  const [exportAgentData, setExportAgentData] = useState<AgentType | undefined>(
    undefined,
  );
  const { permissions } = useContext(AuthContext);
  const isAuth = true;
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const toggleControlPanelAgent = useToggleControlPanelAgent();
  const promoteMutation = usePostControlPanelPromote();
  const validatePublishEmail = useValidatePublishEmail();
  const can = (permissionKey: string) => permissions?.includes(permissionKey);

  const { data, isLoading } = useGetControlPanelAgents(
    {
      env: activeTab.toLowerCase() as "uat" | "prod",
      search: searchQuery || undefined,
      page: 1,
      size: 100,
    },
    {
      refetchInterval: 30000,
    },
  );
  const displayworkflows = useMemo(() => {
    if (workflows?.length) {
      return workflows;
    }

    return (data?.items ?? []).map((item) => ({
      id: item.deploy_id,
      agentId: item.agent_id,
      name: item.agent_name,
      description: item.agent_description ?? "",
      user: item.creator_name ?? "-",
      userEmail: item.creator_email ?? undefined,
      owner: item.owner_name ?? "-",
      ownerCount: item.owner_count ?? 0,
      ownerNames: item.owner_names ?? [],
      ownerEmails: item.owner_emails ?? [],
      department: item.creator_department ?? "-",
      created: formatDateTime(item.created_at),
      movedToProd: item.moved_to_prod ?? false,
      status: item.is_active,
      enabled: item.is_enabled,
    }));
  }, [workflows, data?.items]);

  const normalizedPromoteEmails = useMemo(
    () =>
      Array.from(
        new Set(
          promoteSelectedEmails
            .map((email) => email.trim().toLowerCase())
            .filter(Boolean),
        ),
      ),
    [promoteSelectedEmails],
  );

  const invalidPromoteEmails = useMemo(() => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return normalizedPromoteEmails.filter((email) => !emailRegex.test(email));
  }, [normalizedPromoteEmails]);

  const { data: promoteSharingData, isLoading: isPromoteSharingLoading } =
    useGetControlPanelAgentSharing(
      { deploy_id: selectedPromoteDeployId },
      {
        enabled:
          promoteDialogOpen &&
          selectedPromoteVisibility === "PRIVATE" &&
          Boolean(selectedPromoteDeployId),
      },
    );

  const {
    data: rawPromoteEmailSuggestions = [],
    isFetching: isFetchingPromoteEmailSuggestions,
  } = useGetPublishEmailSuggestions(
    {
      agent_id: selectedPromoteAgentId,
      q: debouncedPromoteEmailQuery,
      limit: 8,
    },
    {
      enabled:
        promoteDialogOpen &&
        selectedPromoteVisibility === "PRIVATE" &&
        !!selectedPromoteAgentId &&
        debouncedPromoteEmailQuery.trim().length > 0,
    },
  );

  const promoteEmailSuggestions = useMemo(
    () =>
      rawPromoteEmailSuggestions.filter(
        (item) =>
          !normalizedPromoteEmails.includes(item.email.trim().toLowerCase()),
      ),
    [rawPromoteEmailSuggestions, normalizedPromoteEmails],
  );

  useEffect(() => {
    const initialStates: {
      [key: string]: { status: boolean; enabled: boolean };
    } = {};
    displayworkflows.forEach((workflow) => {
      initialStates[workflow.id] = {
        status: workflow.status,
        enabled: workflow.enabled,
      };
    });
    setWorkagentStates(initialStates);
  }, [displayworkflows]);

  useEffect(() => {
    if (!promoteDialogOpen) {
      setDebouncedPromoteEmailQuery("");
      return;
    }
    const timer = setTimeout(() => {
      setDebouncedPromoteEmailQuery(promoteEmailDraft.trim().toLowerCase());
    }, 220);
    return () => clearTimeout(timer);
  }, [promoteEmailDraft, promoteDialogOpen]);

  useEffect(() => {
    if (
      !promoteDialogOpen ||
      selectedPromoteVisibility !== "PRIVATE" ||
      promoteRecipientsInitialized
    ) {
      return;
    }
    if (isPromoteSharingLoading) {
      return;
    }
    setPromoteSelectedEmails(promoteSharingData?.recipient_emails ?? []);
    setPromoteRecipientsInitialized(true);
  }, [
    promoteDialogOpen,
    selectedPromoteVisibility,
    promoteRecipientsInitialized,
    isPromoteSharingLoading,
    promoteSharingData?.recipient_emails,
  ]);

  const handleStatusToggle = async (workflowId: string) => {
    const currentStatus = workflowStates[workflowId]?.status ?? false;
    const nextStatus = !currentStatus;
    const env = activeTab.toLowerCase() as "uat" | "prod";

    setWorkagentStates((prev) => ({
      ...prev,
      [workflowId]: {
        ...prev[workflowId],
        status: nextStatus,
      },
    }));
    setPendingToggles((prev) => ({
      ...prev,
      [workflowId]: {
        ...(prev[workflowId] ?? { status: false, enabled: false }),
        status: true,
      },
    }));

    try {
      await toggleControlPanelAgent.mutateAsync({
        deployId: workflowId,
        env,
        field: "is_active",
        value: nextStatus,
      });
    } catch (error: any) {
      setWorkagentStates((prev) => ({
        ...prev,
        [workflowId]: {
          ...prev[workflowId],
          status: currentStatus,
        },
      }));
      setErrorData({
        title: t("Failed to update Start/Stop state"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    } finally {
      setPendingToggles((prev) => ({
        ...prev,
        [workflowId]: {
          ...(prev[workflowId] ?? { status: false, enabled: false }),
          status: false,
        },
      }));
    }
  };

  const handleEnabledToggle = async (workflowId: string) => {
    const currentEnabled = workflowStates[workflowId]?.enabled ?? false;
    const nextEnabled = !currentEnabled;
    const env = activeTab.toLowerCase() as "uat" | "prod";

    setWorkagentStates((prev) => ({
      ...prev,
      [workflowId]: {
        ...prev[workflowId],
        enabled: nextEnabled,
      },
    }));
    setPendingToggles((prev) => ({
      ...prev,
      [workflowId]: {
        ...(prev[workflowId] ?? { status: false, enabled: false }),
        enabled: true,
      },
    }));

    try {
      await toggleControlPanelAgent.mutateAsync({
        deployId: workflowId,
        env,
        field: "is_enabled",
        value: nextEnabled,
      });
    } catch (error: any) {
      setWorkagentStates((prev) => ({
        ...prev,
        [workflowId]: {
          ...prev[workflowId],
          enabled: currentEnabled,
        },
      }));
      setErrorData({
        title: t("Failed to update Enable/Disable state"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    } finally {
      setPendingToggles((prev) => ({
        ...prev,
        [workflowId]: {
          ...(prev[workflowId] ?? { status: false, enabled: false }),
          enabled: false,
        },
      }));
    }
  };

  const setSharingContext = (workflow: WorkagentType) => {
    setSelectedSharingAgentId(workflow.agentId ?? "");
    setSelectedSharingAgentName(workflow.name ?? "");
  };

  const handleOpenWidgetExport = (workflow: WorkagentType) => {
    setSharingContext(workflow);
    setOpenEmbedModal(true);
  };

  const handleOpenExportJson = async (workflow: WorkagentType) => {
    const agentId = workflow.agentId ?? "";
    if (!agentId) {
      setErrorData({
        title: t("Agent not found"),
        list: [t("Unable to load agent data for export.")],
      });
      return;
    }

    try {
      setSharingContext(workflow);
      if (!exportAgentData || exportAgentData.id !== agentId) {
        const response = await api.get(
          `${getURL("PUBLISH")}/${workflow.id}/snapshot`,
        );
        const snapshotPayload = response?.data ?? {};
        const snapshotData = snapshotPayload?.agent_snapshot ?? null;

        const agentForExport: AgentType = {
          id: String(snapshotPayload?.agent_id ?? agentId),
          name: String(snapshotPayload?.agent_name ?? workflow.name ?? "agent"),
          description: String(
            snapshotPayload?.agent_description ?? workflow.description ?? "",
          ),
          data: snapshotData,
          endpoint_name: null,
          tags: [],
          is_component: false,
        };
        setExportAgentData(agentForExport);
      }
      setOpenExportModal(true);
    } catch (error: any) {
      setErrorData({
        title: t("Failed to load agent for export"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    }
  };

  const handlePromoteToProd = async () => {
    if (!selectedPromoteDeployId) return;
    setPromotingById((prev) => ({ ...prev, [selectedPromoteDeployId]: true }));

    if (
      selectedPromoteVisibility === "PRIVATE" &&
      invalidPromoteEmails.length > 0
    ) {
      setErrorData({
        title: t("Invalid email format"),
        list: invalidPromoteEmails,
      });
      setPromotingById((prev) => ({
        ...prev,
        [selectedPromoteDeployId]: false,
      }));
      return;
    }

    if (
      selectedPromoteVisibility === "PRIVATE" &&
      selectedPromoteAgentId &&
      normalizedPromoteEmails.length > 0
    ) {
      try {
        const validationResults = await Promise.all(
          normalizedPromoteEmails.map((email) =>
            validatePublishEmail.mutateAsync({
              agent_id: selectedPromoteAgentId,
              email,
            }),
          ),
        );
        const invalidUsers = validationResults
          .filter((result) => !result.exists_in_department)
          .map((result) => result.email);
        if (invalidUsers.length > 0) {
          setErrorData({
            title: t("Some users are not available in this department."),
            list: invalidUsers,
          });
          setPromotingById((prev) => ({
            ...prev,
            [selectedPromoteDeployId]: false,
          }));
          return;
        }
      } catch (error: any) {
        setErrorData({
          title: t("Email validation failed"),
          list: [
            error?.response?.data?.detail ||
              error?.message ||
              t("Unknown error"),
          ],
        });
        setPromotingById((prev) => ({
          ...prev,
          [selectedPromoteDeployId]: false,
        }));
        return;
      }
    }

    try {
      const response = await promoteMutation.mutateAsync({
        deploy_id: selectedPromoteDeployId,
        visibility: selectedPromoteVisibility,
        recipient_emails:
          selectedPromoteVisibility === "PRIVATE"
            ? normalizedPromoteEmails
            : undefined,
      });
      setSuccessData({
        title: response?.message || t("Promotion request submitted."),
      });
      setPromoteDialogOpen(false);
    } catch (error: any) {
      setErrorData({
        title: t("Failed to move UAT deployment to PROD"),
        list: [
          error?.response?.data?.detail || error?.message || t("Unknown error"),
        ],
      });
    } finally {
      setPromotingById((prev) => ({
        ...prev,
        [selectedPromoteDeployId]: false,
      }));
    }
  };

  const handleOpenPromoteDialog = (workflowId: string) => {
    setSelectedPromoteDeployId(workflowId);
    const workflow = displayworkflows.find((item) => item.id === workflowId);
    setSelectedPromoteAgentId(workflow?.agentId ?? "");
    setSelectedPromoteVisibility("PRIVATE");
    setPromoteSelectedEmails([]);
    setPromoteEmailDraft("");
    setPromoteRecipientsInitialized(false);
    setPromoteDialogOpen(true);
  };

  const addPromoteEmails = (rawValue: string) => {
    const parsed = rawValue
      .split(/[\n,;\s]+/)
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean);
    if (parsed.length === 0) return;

    setPromoteSelectedEmails((prev) => {
      const merged = new Set(prev.map((email) => email.trim().toLowerCase()));
      parsed.forEach((email) => merged.add(email));
      return Array.from(merged);
    });
  };

  const removePromoteEmail = (email: string) => {
    const normalized = email.trim().toLowerCase();
    setPromoteSelectedEmails((prev) =>
      prev.filter((item) => item.trim().toLowerCase() !== normalized),
    );
  };

  const filteredworkflows = displayworkflows.filter((workflow) => {
    const matchesSearch =
      !searchQuery ||
      workflow.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      workflow.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      workflow.user.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (workflow.owner ?? "")
        .toLowerCase()
        .includes(searchQuery.toLowerCase()) ||
      workflow.department.toLowerCase().includes(searchQuery.toLowerCase());

    return matchesSearch;
  });

  useEffect(() => {
    if (!setSearch) return;
    const timer = setTimeout(() => setSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, setSearch]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex-shrink-0 border-b px-8 py-6">
        <div className="mb-4 flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{t("Agent Control Panel")}</h1>
        </div>

        <div className="mb-6 inline-flex rounded-lg border bg-muted/30 p-1">
          <button
            type="button"
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "UAT"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setActiveTab("UAT")}
          >
            UAT
          </button>
          <button
            type="button"
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "PROD"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setActiveTab("PROD")}
          >
            PROD
          </button>
        </div>

        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder={t("Search agents...")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border bg-card py-2.5 pl-10 pr-4 text-sm"
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8">
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                  {t("Agent Name")}
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                  {t("Creator")}
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                  {t("Owner")}
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                  {t("Department")}
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                  {t("Created At")}
                </th>
                {can("view_project_page") && (
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                    {t("Sharing Options")}
                  </th>
                )}
                {can("view_project_page") && (
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                    {t("Move UAT to PROD")}
                  </th>
                )}
                {can("view_project_page") && (
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                    {t("Moved to PROD")}
                  </th>
                )}
                {can("start_stop_agent") && (
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                    {t("Start/Stop")}
                  </th>
                )}
                {can("enable_disable_agent") && (
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                    {t("Enable/Disable")}
                  </th>
                )}
              </tr>
            </thead>

            <tbody className="divide-y">
              {isLoading ? (
                <tr>
                  <td colSpan={11} className="px-6 py-10 text-center">
                    <div className="flex items-center justify-center">
                      <CustomLoader />
                    </div>
                  </td>
                </tr>
              ) : filteredworkflows.length === 0 ? (
                <tr>
                  <td
                    colSpan={11}
                    className="px-6 py-10 text-center text-sm text-muted-foreground"
                  >
                    {t("No deployed agents found")}
                  </td>
                </tr>
              ) : (
                filteredworkflows.map((workflow) => (
                  <tr
                    key={workflow.id}
                    className="cursor-pointer transition-colors hover:bg-muted/50"
                    onClick={() => onWorkagentClick?.(workflow)}
                  >
                    <td className="px-6 py-4">
                      <div className="font-semibold">{workflow.name}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {workflow.description}
                      </div>
                    </td>

                    <td className="px-6 py-4 text-sm">
                      {workflow.userEmail ? (
                        <ShadTooltip content={workflow.userEmail}>
                          <span className="cursor-help">{workflow.user}</span>
                        </ShadTooltip>
                      ) : (
                        workflow.user
                      )}
                    </td>

                    <td className="px-6 py-4 text-sm">
                      <div className="flex items-center gap-1.5">
                        {(workflow.ownerEmails?.length ?? 0) > 0 ? (
                          <ShadTooltip
                            content={(workflow.ownerEmails ?? []).join(", ")}
                          >
                            <span className="cursor-help">
                              {(workflow.ownerCount ?? 0) > 1
                                ? `${workflow.owner ?? "-"} +${(workflow.ownerCount ?? 0) - 1}`
                                : (workflow.owner ?? "-")}
                            </span>
                          </ShadTooltip>
                        ) : (
                          <span>
                            {(workflow.ownerCount ?? 0) > 1
                              ? `${workflow.owner ?? "-"} +${(workflow.ownerCount ?? 0) - 1}`
                              : (workflow.owner ?? "-")}
                          </span>
                        )}
                        {(workflow.ownerNames?.length ?? 0) > 1 && (
                          <ShadTooltip
                            content={(workflow.ownerEmails ?? []).join(", ")}
                          >
                            <span className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-muted-foreground/30 text-muted-foreground">
                              <Info className="h-3 w-3" />
                            </span>
                          </ShadTooltip>
                        )}
                      </div>
                    </td>

                    <td className="px-6 py-4 text-sm">{workflow.department}</td>

                    <td className="px-6 py-4 text-sm text-muted-foreground">
                      {workflow.created}
                    </td>
                    {can("view_project_page") && (
                      <td className="px-6 py-4">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs hover:bg-muted"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <Share2 className="h-3.5 w-3.5" />
                              {t("Share")}
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent
                            align="start"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleOpenExportJson(workflow);
                              }}
                            >
                              {t("Export as JSON")}
                            </DropdownMenuItem>
                            <DropdownMenuItem 
                              onClick={(e) => {
                                e.stopPropagation();
                                handleOpenWidgetExport(workflow);
                              }} disabled
                            >
                              {t("Export as Widget")}
                            </DropdownMenuItem>
                            <DropdownMenuItem disabled>
                              {t("Export as API")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </td>
                    )}
                    {can("view_project_page") && (
                      <td className="px-6 py-4">
                        {activeTab === "UAT" ? (
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                            disabled={promotingById[workflow.id]}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleOpenPromoteDialog(workflow.id);
                            }}
                          >
                            <ArrowUpToLine className="h-3.5 w-3.5" />
                            {promotingById[workflow.id]
                              ? t("Moving...")
                              : t("Move")}
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            -
                          </span>
                        )}
                      </td>
                    )}
                    {can("view_project_page") && (
                      <td className="px-6 py-4 text-xs">
                        {workflow.movedToProd ? (
                          <span className="rounded-full border border-green-200 bg-green-50 px-2 py-1 text-green-700">
                            {t("Yes")}
                          </span>
                        ) : (
                          <span className="rounded-full border border-muted px-2 py-1 text-muted-foreground">
                            {t("No")}
                          </span>
                        )}
                      </td>
                    )}
                    {can("start_stop_agent") && (
                      <td className="px-6 py-4">
                        <button
                          type="button"
                          disabled={pendingToggles[workflow.id]?.status}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                            workflowStates[workflow.id]?.status
                              ? "bg-blue-600"
                              : "bg-muted"
                          }`}
                          onClick={async (e) => {
                            e.stopPropagation();
                            if (pendingToggles[workflow.id]?.status) return;
                            await handleStatusToggle(workflow.id);
                          }}
                        >
                          <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                              workflowStates[workflow.id]?.status
                                ? "translate-x-6"
                                : "translate-x-1"
                            }`}
                          />
                        </button>
                      </td>
                    )}
                    {can("enable_disable_agent") && (
                      <td className="px-6 py-4">
                        <button
                          type="button"
                          disabled={pendingToggles[workflow.id]?.enabled}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                            workflowStates[workflow.id]?.enabled
                              ? "bg-green-500"
                              : "bg-muted"
                          }`}
                          onClick={async (e) => {
                            e.stopPropagation();
                            if (pendingToggles[workflow.id]?.enabled) return;
                            await handleEnabledToggle(workflow.id);
                          }}
                        >
                          <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                              workflowStates[workflow.id]?.enabled
                                ? "translate-x-6"
                                : "translate-x-1"
                            }`}
                          />
                        </button>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-6 flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            {t("Rows per page")}
          </div>
          <div className="flex items-center gap-2">
            <button className="rounded-lg border bg-card px-4 py-2 text-sm hover:bg-muted">
              {t("Previous")}
            </button>
            <button className="rounded-lg border bg-card px-4 py-2 text-sm hover:bg-muted">
              {t("Next")}
            </button>
          </div>
        </div>
      </div>

      <ExportModal
        open={openExportModal}
        setOpen={setOpenExportModal}
        agentData={exportAgentData}
      />
      <Dialog open={promoteDialogOpen} onOpenChange={setPromoteDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("Move UAT to PROD")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
              {t("Select visibility for PROD deployment.")}
            </div>
            <div className="space-y-2 rounded-md border p-3">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="promote-public"
                  checked={selectedPromoteVisibility === "PUBLIC"}
                  onCheckedChange={(checked) => {
                    if (checked === true) {
                      setSelectedPromoteVisibility("PUBLIC");
                    }
                  }}
                />
                <Label htmlFor="promote-public">{t("Public")}</Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="promote-private"
                  checked={selectedPromoteVisibility === "PRIVATE"}
                  onCheckedChange={(checked) => {
                    if (checked === true) {
                      setSelectedPromoteVisibility("PRIVATE");
                    }
                  }}
                />
                <Label htmlFor="promote-private">{t("Private")}</Label>
              </div>
            </div>
            {selectedPromoteVisibility === "PRIVATE" && (
              <div className="space-y-2 rounded-md border p-3">
                <Label htmlFor="promote-emails" className="text-sm font-medium">
                  {t("Assigned users")}
                </Label>
                <div className="rounded-md border bg-background px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {normalizedPromoteEmails.map((email) => (
                      <span
                        key={email}
                        className="inline-flex items-center gap-1 rounded-full border bg-slate-100 px-2 py-1 text-xs text-slate-700"
                      >
                        <span className="max-w-[220px] truncate">{email}</span>
                        <button
                          type="button"
                          onClick={() => removePromoteEmail(email)}
                          className="rounded p-0.5 text-slate-500 hover:bg-slate-200 hover:text-slate-700"
                          aria-label={`Remove ${email}`}
                        >
                          <span className="text-[11px] leading-none">x</span>
                        </button>
                      </span>
                    ))}
                    <input
                      id="promote-emails"
                      value={promoteEmailDraft}
                      onChange={(event) =>
                        setPromoteEmailDraft(event.target.value)
                      }
                      onKeyDown={(event) => {
                        if (
                          ["Enter", "Tab", ",", ";", " "].includes(event.key)
                        ) {
                          if (!promoteEmailDraft.trim()) return;
                          event.preventDefault();
                          addPromoteEmails(promoteEmailDraft);
                          setPromoteEmailDraft("");
                          return;
                        }
                        if (
                          event.key === "Backspace" &&
                          !promoteEmailDraft.trim() &&
                          normalizedPromoteEmails.length > 0
                        ) {
                          const lastEmail =
                            normalizedPromoteEmails[
                              normalizedPromoteEmails.length - 1
                            ];
                          if (lastEmail) removePromoteEmail(lastEmail);
                        }
                      }}
                      onBlur={() => {
                        if (promoteEmailDraft.trim()) {
                          addPromoteEmails(promoteEmailDraft);
                          setPromoteEmailDraft("");
                        }
                      }}
                      onPaste={(event) => {
                        const pasted = event.clipboardData.getData("text");
                        if (!pasted) return;
                        if (/[,;\n\s]/.test(pasted)) {
                          event.preventDefault();
                          addPromoteEmails(pasted);
                        }
                      }}
                      placeholder={
                        normalizedPromoteEmails.length === 0
                          ? "Type email and press Enter"
                          : "Add more users"
                      }
                      className="min-w-[180px] flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                    />
                  </div>
                  {promoteEmailDraft.trim().length > 0 && (
                    <div className="mt-2 rounded-md border bg-white shadow-sm">
                      {isFetchingPromoteEmailSuggestions ? (
                        <div className="px-3 py-2 text-xs text-muted-foreground">
                          Searching users...
                        </div>
                      ) : promoteEmailSuggestions.length > 0 ? (
                        <div className="max-h-44 overflow-auto py-1">
                          {promoteEmailSuggestions.map((item) => (
                            <button
                              key={item.email}
                              type="button"
                              className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-100"
                              onMouseDown={(event) => {
                                event.preventDefault();
                                addPromoteEmails(item.email);
                                setPromoteEmailDraft("");
                              }}
                            >
                              <span className="truncate">{item.email}</span>
                              {item.display_name && (
                                <span className="ml-2 truncate text-xs text-muted-foreground">
                                  {item.display_name}
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <div className="px-3 py-2 text-xs text-muted-foreground">
                          No department suggestions found.
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  {t(
                    "Private PROD visibility: only assigned users, creator and admins can access.",
                  )}
                </p>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setPromoteDialogOpen(false)}
              >
                {t("Cancel")}
              </Button>
              <Button
                onClick={() => void handlePromoteToProd()}
                disabled={
                  !selectedPromoteDeployId ||
                  promotingById[selectedPromoteDeployId]
                }
              >
                {promotingById[selectedPromoteDeployId]
                  ? t("Moving...")
                  : t("Move")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <EmbedModal
        open={openEmbedModal}
        setOpen={setOpenEmbedModal}
        agentId={selectedSharingAgentId}
        agentName={selectedSharingAgentName}
        isAuth={isAuth}
        tweaksBuildedObject={{}}
        activeTweaks={false}
      />
    </div>
  );
}
