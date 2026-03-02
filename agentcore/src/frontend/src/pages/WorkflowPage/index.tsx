import {
  Search,
  X
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useContext } from "react";
import { useTranslation } from "react-i18next";
import { AuthContext } from "@/contexts/authContext";
import CustomLoader from "@/customization/components/custom-loader";
import { useGetControlPanelAgents } from "@/controllers/API/queries/control-panel";

type EnvironmentTab = "UAT" | "PROD";

interface WorkagentType {
  id: string;
  name: string;
  description: string;
  user: string;
  department: string;
  created: string;
  lastRun: string;
  failedRuns: number | null;
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
  const { permissions } = useContext(AuthContext);
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
      keepPreviousData: true,
    },
  );

  const displayworkflows = useMemo(() => {
    if (workflows?.length) {
      return workflows;
    }

    return (data?.items ?? []).map((item) => ({
      id: item.deploy_id,
      name: item.agent_name,
      description: item.agent_description ?? "",
      user: item.creator_name ?? "-",
      department: item.creator_department ?? "-",
      created: formatDateTime(item.created_at),
      lastRun: formatDateTime(item.last_run),
      failedRuns: item.failed_runs ?? 0,
      status: item.is_active,
      enabled: item.is_enabled,
    }));
  }, [workflows, data?.items]);

  useEffect(() => {
    const initialStates: { [key: string]: { status: boolean; enabled: boolean } } = {};
    displayworkflows.forEach((workflow) => {
      initialStates[workflow.id] = {
        status: workflow.status,
        enabled: workflow.enabled,
      };
    });
    setWorkagentStates(initialStates);
  }, [displayworkflows]);

  const handleStatusToggle = (workflowId: string) => {
    setWorkagentStates((prev) => ({
      ...prev,
      [workflowId]: {
        ...prev[workflowId],
        status: !prev[workflowId]?.status,
      },
    }));
  };

  const handleEnabledToggle = (workflowId: string) => {
    setWorkagentStates((prev) => ({
      ...prev,
      [workflowId]: {
        ...prev[workflowId],
        enabled: !prev[workflowId]?.enabled,
      },
    }));
  };

  const filteredworkflows = displayworkflows.filter((workflow) => {
    const matchesSearch =
      !searchQuery ||
      workflow.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      workflow.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      workflow.user.toLowerCase().includes(searchQuery.toLowerCase()) ||
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
                  {t("Department")}
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                  {t("Created At")}
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                  {t("Last Run")}
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase">
                  {t("Failed Runs")}
                </th>
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
                  <td colSpan={8} className="px-6 py-10 text-center">
                    <div className="flex items-center justify-center">
                      <CustomLoader />
                    </div>
                  </td>
                </tr>
              ) : filteredworkflows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-6 py-10 text-center text-sm text-muted-foreground">
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

                  <td className="px-6 py-4 text-sm">{workflow.user}</td>

                  <td className="px-6 py-4 text-sm">{workflow.department}</td>

                  <td className="px-6 py-4 text-sm text-muted-foreground">{workflow.created}</td>

                  <td className="px-6 py-4 text-sm text-muted-foreground">{workflow.lastRun}</td>

                  <td className="px-6 py-4">
                    {workflow.failedRuns !== null ? (
                      <div className="flex items-center gap-1.5 text-sm text-red-500">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full border border-red-500">
                          <X className="h-3 w-3" />
                        </span>
                        <span className="font-medium">{workflow.failedRuns}</span>
                      </div>
                    ) : (
                      <span className="text-sm text-muted-foreground">-</span>
                    )}
                  </td>
                  {can("start_stop_agent") && (
                    <td className="px-6 py-4">
                      <button
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          workflowStates[workflow.id]?.status ? "bg-blue-600" : "bg-muted"
                        }`}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleStatusToggle(workflow.id);
                        }}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            workflowStates[workflow.id]?.status ? "translate-x-6" : "translate-x-1"
                          }`}
                        />
                      </button>
                    </td>
                  )}
                  {can("enable_disable_agent") && (
                    <td className="px-6 py-4">
                      <button
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          workflowStates[workflow.id]?.enabled ? "bg-green-500" : "bg-muted"
                        }`}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleEnabledToggle(workflow.id);
                        }}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            workflowStates[workflow.id]?.enabled ? "translate-x-6" : "translate-x-1"
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
          <div className="text-sm text-muted-foreground">{t("Rows per page")}</div>
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
    </div>
  );
}
