import { Edit2, Eye, History, MoreVertical, Plus, Search, Shield, Trash2, ArrowLeft } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import Loading from "@/components/ui/loading";
import { AuthContext } from "@/contexts/authContext";
import {
  type GuardrailEnvironment,
  type GuardrailInfo,
  useDeleteGuardrailCatalogue,
  useGetGuardrailsCatalogue,
} from "@/controllers/API/queries/guardrails";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import useAlertStore from "@/stores/alertStore";
import NvidiaLogo from "@/assets/nvidia_logo.svg?react";
import EditGuardrailModal from "./components/edit-guardrail-modal";
import GuardrailFrameworksList from "./components/guardrail-frameworks-list";
import GuardrailVersionHistory from "./components/guardrail-version-history";

interface GuardrailsViewProps {
  guardrails?: GuardrailInfo[];
  setSearch?: (search: string) => void;
}

interface GuardrailFramework {
  id: string;
  name: string;
  description: string;
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
}

type CategoryType =
  | "all"
  | "content-safety"
  | "jailbreak"
  | "topic-control"
  | "pii-detection";

// Available guardrail frameworks
const GUARDRAIL_FRAMEWORKS: GuardrailFramework[] = [
  {
    id: "nemo-guardrails",
    name: "NeMo Guardrails",
    description: "NVIDIA's NeMo Guardrails framework for LLM safety and moderation with configurable policies",
    icon: NvidiaLogo,
  }
];

export default function GuardrailsView({
  guardrails = [],
  setSearch = () => {},
}: GuardrailsViewProps): JSX.Element {
  const { t } = useTranslation();
  const [filter] = useState<CategoryType>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedGuardrail, setSelectedGuardrail] =
    useState<GuardrailInfo | null>(null);
  const [selectedFramework, setSelectedFramework] =
    useState<GuardrailFramework | null>(null);
  const [versionHistoryGuardrail, setVersionHistoryGuardrail] =
    useState<GuardrailInfo | null>(null);
  const [selectedEnvironment, setSelectedEnvironment] =
    useState<GuardrailEnvironment>("uat");
  const isProdView = selectedEnvironment === "prod";

  const { permissions, role, userData } = useContext(AuthContext);
  const can = (permission: string) => permissions?.includes(permission);
  const canAddGuardrails = can("add_guardrails");
  const canCreateOrEdit = canAddGuardrails && !isProdView;
  const canDelete = can("retire_guardrails") && !isProdView;
  const canManage = canCreateOrEdit || canDelete;
  const isDepartmentAdmin = role === "department_admin";
  const isSuperAdmin = role === "super_admin";
  const userDeptId = userData?.department_id ?? null;
  const userId = userData?.id ?? null;

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const selectedFrameworkId =
    selectedFramework?.id === "nemo-guardrails"
      ? "nemo"
      : selectedFramework?.id === "arize-guardrails"
        ? "arize"
        : undefined;
  const { data: dbGuardrails, isLoading, error } = useGetGuardrailsCatalogue(
    { framework: selectedFrameworkId, environment: selectedEnvironment },
  );
  const deleteMutation = useDeleteGuardrailCatalogue();
  const [visibilityOptions, setVisibilityOptions] = useState<{
    organizations: { id: string; name: string }[];
    departments: { id: string; name: string; org_id: string }[];
  }>({ organizations: [], departments: [] });

  const displayGuardrails = guardrails?.length
    ? guardrails
    : (dbGuardrails ?? []);

  const filteredGuardrails = displayGuardrails.filter((guardrail) => {
    const matchesFilter = filter === "all" || guardrail.category === filter;
    const matchesSearch =
      !searchQuery ||
      guardrail.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      guardrail.description?.toLowerCase().includes(searchQuery.toLowerCase());

    return matchesFilter && matchesSearch;
  });

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, setSearch]);

  useEffect(() => {
    if (!selectedFramework || (!isDepartmentAdmin && !isSuperAdmin)) return;
    api
      .get(`${getURL("GUARDRAILS_CATALOGUE")}/visibility-options`)
      .then((res) => {
        setVisibilityOptions({
          organizations: res.data?.organizations || [],
          departments: res.data?.departments || [],
        });
      })
      .catch(() => {
        setVisibilityOptions({ organizations: [], departments: [] });
      });
  }, [selectedFramework, isDepartmentAdmin, isSuperAdmin]);

  const getCategoryLabel = (category: string) => {
    const labels: Record<string, string> = {
      "content-safety": "Content Safety",
      jailbreak: "Jailbreak Prevention",
      "topic-control": "Topic Control",
      "pii-detection": "PII Detection",
    };
    return labels[category] || category;
  };

  const getCategoryBadgeColor = (category: string) => {
    const colors: Record<string, string> = {
      "content-safety":
        "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
      jailbreak:
        "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
      "topic-control":
        "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
      "pii-detection":
        "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
    };
    return (
      colors[category] ||
      "bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400"
    );
  };
  const getVisibilityLabel = (guardrail: GuardrailInfo) => {
    if (guardrail.visibility === "public") {
      return guardrail.public_scope === "organization" ? "Organization" : "Department";
    }
    return "Private";
  };
  const getVisibilityBadgeClass = (guardrail: GuardrailInfo) => {
    if (guardrail.visibility === "public") {
      return guardrail.public_scope === "organization"
        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
        : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
    }
    return "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200";
  };
  const getDepartmentScopeLabel = (guardrail: GuardrailInfo) => {
    const deptNameById = new Map(
      visibilityOptions.departments.map((dept) => [String(dept.id), dept.name]),
    );
    if (guardrail.visibility === "public" && guardrail.public_scope === "organization") {
      const orgId = guardrail.org_id ? String(guardrail.org_id) : "";
      const orgName =
        visibilityOptions.organizations.find((org) => String(org.id) === orgId)
          ?.name || null;
      return orgName ? `${orgName} (All departments)` : "All departments";
    }
    const deptIds =
      guardrail.visibility === "public" && guardrail.public_scope === "department"
        ? guardrail.public_dept_ids?.length
          ? guardrail.public_dept_ids
          : guardrail.dept_id
            ? [guardrail.dept_id]
            : []
        : guardrail.dept_id
          ? [guardrail.dept_id]
          : [];
    if (deptIds.length === 0) return "-";
    const names = deptIds.map((id) => {
      const key = String(id);
      return deptNameById.get(key) || key;
    });
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  };

  const getGuardrailDeptIds = (guardrail: GuardrailInfo) => {
    const ids = new Set<string>();
    (guardrail.public_dept_ids || []).forEach((id) => ids.add(id));
    if (guardrail.dept_id) ids.add(guardrail.dept_id);
    return Array.from(ids);
  };

  const isMultiDeptGuardrail = (guardrail: GuardrailInfo) =>
    guardrail.visibility === "public" &&
    guardrail.public_scope === "department" &&
    getGuardrailDeptIds(guardrail).length > 1;

  const isDeptScopedForUser = (guardrail: GuardrailInfo) =>
    Boolean(userDeptId && getGuardrailDeptIds(guardrail).includes(userDeptId));

  const canEditGuardrail = (guardrail: GuardrailInfo) => {
    if (!canCreateOrEdit) return false;
    if (role === "root") {
      return (
        guardrail.created_by_id === userId &&
        !guardrail.org_id &&
        !guardrail.dept_id
      );
    }
    if (role === "super_admin") return true;
    if (role === "department_admin") {
      if (isMultiDeptGuardrail(guardrail)) return false;
      if (guardrail.visibility === "public" && guardrail.public_scope === "organization") return false;
      if (guardrail.visibility === "public" && guardrail.public_scope === "department") {
        return isDeptScopedForUser(guardrail);
      }
      if (guardrail.visibility === "private") return isDeptScopedForUser(guardrail);
      return false;
    }
    if (role === "developer" || role === "business_user") {
      return guardrail.visibility === "private" && guardrail.created_by_id === userId;
    }
    return false;
  };

  const canDeleteGuardrail = (guardrail: GuardrailInfo) => {
    if (!canDelete) return false;
    if (role === "root") {
      return (
        guardrail.created_by_id === userId &&
        !guardrail.org_id &&
        !guardrail.dept_id
      );
    }
    if (role === "super_admin") return true;
    if (role === "department_admin") {
      if (isMultiDeptGuardrail(guardrail)) return false;
      if (guardrail.visibility === "public" && guardrail.public_scope === "organization") return false;
      if (guardrail.visibility === "public" && guardrail.public_scope === "department") {
        return isDeptScopedForUser(guardrail);
      }
      if (guardrail.visibility === "private") return isDeptScopedForUser(guardrail);
      return false;
    }
    if (role === "developer" || role === "business_user") {
      return guardrail.visibility === "private" && guardrail.created_by_id === userId;
    }
    return false;
  };

  const handleCreateGuardrail = () => {
    setSelectedGuardrail(null);
    setIsEditModalOpen(true);
  };

  const handleSelectFramework = (framework: GuardrailFramework) => {
    setSelectedFramework(framework);
  };

  const handleBackToFrameworks = () => {
    setSelectedFramework(null);
  };

  const handleEditGuardrail = (guardrail: GuardrailInfo) => {
    setSelectedGuardrail(guardrail);
    setIsEditModalOpen(true);
  };

  const handleDeleteGuardrail = async (guardrail: GuardrailInfo) => {
    const shouldDelete = window.confirm(
      t('Delete guardrail "{{name}}"?', { name: guardrail.name }),
    );
    if (!shouldDelete) return;

    try {
      await deleteMutation.mutateAsync({ id: guardrail.id });
      setSuccessData({ title: t('Guardrail "{{name}}" deleted.', { name: guardrail.name }) });
    } catch {
      setErrorData({ title: t("Failed to delete guardrail.") });
    }
  };

  return (
    <>
      {!selectedFramework ? (
        <GuardrailFrameworksList
          frameworks={GUARDRAIL_FRAMEWORKS}
          onSelectFramework={handleSelectFramework}
          isLoading={false}
        />
      ) : (
        <div className="flex h-full w-full flex-col overflow-hidden">
          <div className="flex flex-shrink-0 flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 md:px-8 md:py-4">
            <div>
              <div className="mb-1 flex items-center gap-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleBackToFrameworks}
                  className="h-8 w-8 p-0"
                >
                  <ArrowLeft className="h-4 w-4" />
                </Button>
                <h1 className="text-xl font-semibold">{t("{{name}} Policies", { name: selectedFramework.name })}</h1>
              </div>
              <p className="text-sm text-muted-foreground">
                {isProdView
                  ? t(
                      "Frozen production versions for {{name}} — read-only. Edits happen in UAT and are versioned on agent deploy.",
                      { name: selectedFramework.name },
                    )
                  : t("Manage and configure guardrail policies for {{name}}", {
                      name: selectedFramework.name,
                    })}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center rounded-lg border border-border bg-muted/50 p-1">
                {([
                  { value: "uat" as const, label: t("UAT") },
                  { value: "prod" as const, label: t("PROD") },
                ] as const).map((env) => (
                  <button
                    key={env.value}
                    onClick={() => setSelectedEnvironment(env.value)}
                    className={`rounded-md px-4 py-1.5 text-sm font-medium transition-all ${
                      selectedEnvironment === env.value
                        ? "bg-[var(--button-primary)] text-[var(--button-primary-foreground)] shadow-sm"
                        : "text-muted-foreground hover:bg-muted"
                    }`}
                  >
                    {env.label}
                  </button>
                ))}
              </div>

              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  placeholder={t("Search guardrails...")}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-64 rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <Button
                onClick={handleCreateGuardrail}
                disabled={isProdView || !canAddGuardrails}
                title={
                  isProdView
                    ? t("Production view is read-only")
                    : !canAddGuardrails
                      ? t("You do not have permission to add guardrails")
                      : undefined
                }
              >
                <Plus className="mr-2 h-4 w-4" />
                {t("Add Guardrail")}
              </Button>
            </div>
          </div>

          <div className="flex-1 overflow-auto p-4 sm:p-6">
            {isLoading ? (
              <div className="flex h-full w-full items-center justify-center">
                <Loading />
              </div>
            ) : (
              <>
                {!!error && (
                  <div className="mb-4 rounded-md border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                    {t("Failed to load guardrails from database.")}
                  </div>
                )}
                <div className="overflow-x-auto rounded-lg border border-border bg-card">
                  <table className="w-full">
                    <thead className="bg-muted/50">
                      <tr className="border-b border-border">
                        {[
                          "Guardrail Name",
                          "Model",
                          "Visibility",
                          ...(isDepartmentAdmin ? ["Created By"] : []),
                          ...(isSuperAdmin ? ["Department Scope"] : []),
                          "Category",
                          "Status",
                          ...(canManage || isProdView ? ["Actions"] : []),
                        ].map((h) => (
                          <th
                            key={h}
                            className="px-4 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>

                    <tbody className="divide-y divide-border">
                      {filteredGuardrails.length === 0 ? (
                        <tr>
                          <td
                            colSpan={5 + (isDepartmentAdmin ? 1 : 0) + (isSuperAdmin ? 1 : 0) + (canManage || isProdView ? 1 : 0)}
                            className="px-4 py-12 text-center text-muted-foreground"
                          >
                            No guardrails found matching your criteria
                          </td>
                        </tr>
                      ) : (
                        filteredGuardrails.map((guardrail) => (
                          <tr
                            key={guardrail.id}
                            className="group hover:bg-muted/50"
                          >
                            <td className="px-4 py-4">
                              <div className="flex items-center gap-2">
                                <div
                                  className="max-w-[260px] line-clamp-2 font-semibold leading-6"
                                  title={guardrail.name}
                                >
                                  {guardrail.name}
                                </div>
                                {guardrail.isCustom && (
                                  <span className="inline-flex rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                                    Custom
                                  </span>
                                )}
                                {(guardrail.latestVersion ?? 0) > 0 && (
                                  <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                                    <Shield className="h-3 w-3" />
                                    v{guardrail.latestVersion}
                                  </span>
                                )}
                              </div>
                              {guardrail.description && (
                                <div
                                  className="mt-1 max-w-[260px] line-clamp-1 text-xs text-muted-foreground"
                                  title={guardrail.description}
                                >
                                  {guardrail.description}
                                </div>
                              )}
                              {guardrail.runtimeReady === true && (
                                <div className="mt-1 text-xxs text-emerald-600 dark:text-emerald-400">
                                  Runtime ready
                                </div>
                              )}
                              {guardrail.runtimeConfig &&
                                guardrail.runtimeReady === false && (
                                  <div className="mt-1 text-xxs text-amber-600 dark:text-amber-400">
                                    Runtime config incomplete
                                  </div>
                                )}
                            </td>

                            <td className="px-4 py-4">
                              <div
                                className="max-w-[220px] line-clamp-2 text-sm font-medium leading-6"
                                title={
                                  guardrail.modelDisplayName ||
                                  guardrail.modelName ||
                                  "Not linked"
                                }
                              >
                                {guardrail.modelDisplayName ||
                                  guardrail.modelName ||
                                  "Not linked"}
                              </div>
                              {guardrail.modelName &&
                                guardrail.modelDisplayName && (
                                  <div
                                    className="mt-1 max-w-[220px] truncate text-xs text-muted-foreground"
                                    title={guardrail.modelName}
                                  >
                                    {guardrail.modelName}
                                  </div>
                                )}
                            </td>

                            <td className="px-4 py-4">
                              <span
                                className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${getVisibilityBadgeClass(guardrail)}`}
                              >
                                {getVisibilityLabel(guardrail)}
                              </span>
                            </td>

                            {isDepartmentAdmin && (
                              <td className="px-4 py-4 text-sm text-muted-foreground">
                                <div
                                  className="max-w-[170px] truncate"
                                  title={guardrail.created_by_email || guardrail.created_by || "-"}
                                >
                                  {guardrail.created_by || "-"}
                                </div>
                              </td>
                            )}

                            {isSuperAdmin && (
                              <td className="px-4 py-4 text-sm text-muted-foreground">
                                <div
                                  className="max-w-[170px] truncate"
                                  title={getDepartmentScopeLabel(guardrail)}
                                >
                                  {getDepartmentScopeLabel(guardrail)}
                                </div>
                              </td>
                            )}

                            <td className="px-4 py-4">
                              <span
                                className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${getCategoryBadgeColor(guardrail.category)}`}
                              >
                                {getCategoryLabel(guardrail.category)}
                              </span>
                            </td>

                            <td className="px-4 py-4">
                              <div className="flex items-center gap-2">
                                <span
                                  className={`h-2 w-2 rounded-full ${guardrail.status === "active" ? "bg-green-500" : "bg-gray-400"}`}
                                ></span>
                                <span className="text-sm capitalize">
                                  {guardrail.status}
                                </span>
                              </div>
                            </td>

                            {isProdView && (
                              <td className="px-4 py-4">
                                <button
                                  onClick={() =>
                                    setVersionHistoryGuardrail(guardrail)
                                  }
                                  className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
                                >
                                  <Eye className="h-4 w-4" />
                                  {t("View Active Version")}
                                </button>
                              </td>
                            )}
                            {canManage && !isProdView && (
                              <td className="px-4 py-4">
                                {canEditGuardrail(guardrail) ||
                                canDeleteGuardrail(guardrail) ? (
                                  <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                      <button className="rounded p-1 hover:bg-muted">
                                        <MoreVertical className="h-4 w-4" />
                                      </button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                      {canEditGuardrail(guardrail) && (
                                        <DropdownMenuItem
                                          onClick={() =>
                                            handleEditGuardrail(guardrail)
                                          }
                                        >
                                          <Edit2 className="mr-2 h-4 w-4" />
                                          Edit
                                        </DropdownMenuItem>
                                      )}
                                      <DropdownMenuItem
                                        onClick={() =>
                                          setVersionHistoryGuardrail(guardrail)
                                        }
                                      >
                                        <History className="mr-2 h-4 w-4" />
                                        Version History
                                      </DropdownMenuItem>
                                      {canDeleteGuardrail(guardrail) && (
                                        <DropdownMenuItem
                                          onClick={() =>
                                            handleDeleteGuardrail(guardrail)
                                          }
                                          className="text-destructive"
                                        >
                                          <Trash2 className="mr-2 h-4 w-4" />
                                          Delete
                                        </DropdownMenuItem>
                                      )}
                                    </DropdownMenuContent>
                                  </DropdownMenu>
                                ) : (
                                  <span className="text-muted-foreground">
                                    -
                                  </span>
                                )}
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="mt-6 text-center text-sm text-muted-foreground">
                  Showing {filteredGuardrails.length} of {displayGuardrails.length}{" "}
                  guardrails
                </div>
              </>
            )}
          </div>

          <EditGuardrailModal
            open={isEditModalOpen}
            onOpenChange={setIsEditModalOpen}
            guardrail={selectedGuardrail}
            frameworkId={selectedFrameworkId}
          />
          <GuardrailVersionHistory
            guardrail={versionHistoryGuardrail}
            open={versionHistoryGuardrail !== null}
            onOpenChange={(open) => {
              if (!open) setVersionHistoryGuardrail(null);
            }}
          />
        </div>
      )}
    </>
  );
}
