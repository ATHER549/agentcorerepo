import {
  Plus,
  MoreVertical,
  Edit2,
  Trash2,
  Search,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
} from "lucide-react";
import { useContext, useEffect, useMemo, useState } from "react";
import type { ModelType, ModelEnvironment, ModelTypeFilter } from "@/types/models/models";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import EditModelModal from "./components/edit-model-modal";
import RequestModelModal from "./components/request-model-modal";
import { getProviderIcon } from "@/utils/logo_provider";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import useAlertStore from "@/stores/alertStore";
import { useTranslation } from "react-i18next";
import {
  useGetRegistryModels,
  useDeleteRegistryModel,
} from "@/controllers/API/queries/models";

type ProviderFilter = "all" | string;
type EnvFilter = "all" | ModelEnvironment;
type VisibilityOptions = {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
};

const PROVIDER_LABELS: Record<string, string> = {
  all: "All",
  openai: "OpenAI",
  azure: "Azure",
  anthropic: "Anthropic",
  google: "Google",
  groq: "Groq",
  openai_compatible: "Custom",
};

const ENV_LABELS: Record<string, string> = {
  all: "All Envs",
  test: "DEV",
  uat: "UAT",
  prod: "PROD",
};

const ENV_BADGE_CLASSES: Record<string, string> = {
  test: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
  uat: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  prod: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
};

const VISIBILITY_LABELS: Record<string, string> = {
  private: "Private",
  department: "Department",
  organization: "Organization",
};

const VISIBILITY_BADGE_CLASSES: Record<string, string> = {
  private: "bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-400",
  department: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400",
  organization: "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400",
};

const MODEL_TYPE_LABELS: Record<string, string> = {
  llm: "LLMs",
  embedding: "Embeddings",
};

export default function ModelCatalogue(): JSX.Element {
  const { t } = useTranslation();
  const [modelTypeFilter, setModelTypeFilter] = useState<ModelTypeFilter>("llm");
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>("all");
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isRequestModalOpen, setIsRequestModalOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState<ModelType | null>(null);
  const [deleteConfirmModel, setDeleteConfirmModel] = useState<ModelType | null>(null);
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
  });

  const { permissions, role } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const normalizedRole = (role ?? "").toLowerCase();
  const isModelAdmin =
    normalizedRole === "root" ||
    normalizedRole === "super_admin" ||
    normalizedRole === "department_admin";
  const canAddModel = isModelAdmin && can("add_new_model");
  const canRequestModel = can("request_new_model");
  const isDepartmentAdmin = normalizedRole === "department_admin";
  const isSuperAdmin = normalizedRole === "super_admin";

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  // Fetch models from API
  const { data: models, isLoading, isError } = useGetRegistryModels({
    active_only: false,
  });

  const deleteMutation = useDeleteRegistryModel();

  useEffect(() => {
    api
      .get("api/mcp/registry/visibility-options")
      .then((res) => {
        const options: VisibilityOptions = res.data || {
          organizations: [],
          departments: [],
        };
        setVisibilityOptions(options);
      })
      .catch(() => {
        setVisibilityOptions({ organizations: [], departments: [] });
      });
  }, []);

  const deptById = useMemo(
    () =>
      new Map(
        visibilityOptions.departments.map((dept) => [dept.id, dept] as const),
      ),
    [visibilityOptions.departments],
  );

  const displayModels = models ?? [];
  const defaultProviders = (Object.keys(PROVIDER_LABELS) as ProviderFilter[]).filter(
    (p) => p !== "all",
  );
  const dataProviders = Array.from(new Set(displayModels.map((m) => m.provider))).filter(
    (p) => !defaultProviders.includes(p),
  );
  const availableProviders: ProviderFilter[] = ["all", ...defaultProviders, ...dataProviders.sort()];

  /* ---------------------------------- Filtering ---------------------------------- */

  const filteredModels = displayModels.filter((model) => {
    const matchesType = model.model_type === modelTypeFilter;
    const matchesProvider =
      providerFilter === "all" || model.provider === providerFilter;
    const matchesEnv =
      envFilter === "all" || model.environment === envFilter;
    const matchesSearch =
      !searchQuery ||
      model.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      model.model_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      model.description?.toLowerCase().includes(searchQuery.toLowerCase());

    return matchesType && matchesProvider && matchesEnv && matchesSearch;
  });

  /* ---------------------------------- Helpers ---------------------------------- */

  const getProviderLogo = (provider: string) => {
    const iconSrc = getProviderIcon(provider);
    return (
      <img
        src={iconSrc}
        alt={`${provider} icon`}
        className="h-4 w-4 object-contain"
      />
    );
  };

  const getProviderName = (provider: string) =>
    PROVIDER_LABELS[provider] ?? provider;

  const handleDeleteConfirm = async () => {
    if (!deleteConfirmModel) return;
    try {
      await deleteMutation.mutateAsync({ id: deleteConfirmModel.id });
      setSuccessData({
        title: t("Model \"{{name}}\" deleted.", { name: deleteConfirmModel.display_name }),
      });
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail ||
        err?.message ||
        t("You do not have permission to delete this model.");
      setErrorData({ title: t("Failed to delete model."), list: [detail] });
    }
    setDeleteConfirmModel(null);
  };

  /* ---------------------------------- JSX ---------------------------------- */

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 flex items-center justify-between border-b px-8 py-6">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{t("Model Registry")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Onboard, browse, and manage AI models across environments")}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={t("Search models...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-64 rounded-lg border bg-card py-2.5 pl-10 pr-4 text-sm"
            />
          </div>

          {canAddModel ? (
            <ShadTooltip
              content={
                !canAddModel
                  ? t("You don't have permission to add models")
                  : ""
              }
            >
              <span className="inline-block">
                <Button
                  onClick={() => {
                    setSelectedModel(null);
                    setIsEditModalOpen(true);
                  }}
                  disabled={!canAddModel}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  {modelTypeFilter === "embedding" ? t("Add Embedding") : t("Add Model")}
                </Button>
              </span>
            </ShadTooltip>
          ) : canRequestModel ? (
            <Button onClick={() => setIsRequestModalOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              {modelTypeFilter === "embedding" ? t("Add / Request Embedding") : t("Add / Request Model")}
            </Button>
          ) : null}
        </div>
      </div>

      {/* Filters */}
      <div className="flex-shrink-0 border-b px-8 py-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {t("Model Type")}
            </p>
            <div className="flex gap-2">
              {(["llm", "embedding"] as ModelTypeFilter[]).map((type) => (
                <Button
                  key={type}
                  size="sm"
                  variant={modelTypeFilter === type ? "default" : "outline"}
                  className="flex-1"
                  onClick={() => setModelTypeFilter(type)}
                >
                  {t(MODEL_TYPE_LABELS[type])}
                </Button>
              ))}
            </div>
          </div>

          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {t("Provider")}
            </p>
            <Select
              value={providerFilter}
              onValueChange={(value) => setProviderFilter(value)}
            >
              <SelectTrigger className="w-full bg-card">
                <SelectValue placeholder={t("All")} />
              </SelectTrigger>
              <SelectContent>
                {availableProviders.map((provider) => (
                  <SelectItem key={provider} value={provider}>
                    {t(getProviderName(provider))}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {t("Environment")}
            </p>
            <Select
              value={envFilter}
              onValueChange={(value) => setEnvFilter(value as EnvFilter)}
            >
              <SelectTrigger className="w-full bg-card">
                <SelectValue placeholder={t("All Envs")} />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ENV_LABELS) as EnvFilter[]).map((env) => (
                  <SelectItem key={env} value={env}>
                    {t(ENV_LABELS[env])}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-end">
            <Button
              variant="outline"
              className="w-full"
              onClick={() => {
                setProviderFilter("all");
                setEnvFilter("all");
                setSearchQuery("");
              }}
            >
              {t("Reset Filters")}
            </Button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto p-8">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center py-20 text-destructive">
            {t("Failed to load models. Please try again.")}
          </div>
        ) : (
          <>
            <div className="rounded-lg border bg-card overflow-x-auto">
              <table className="w-full">
                <thead className="bg-muted/50">
                  <tr>
                    {[
                      "Model",
                      "Provider",
                      "Model ID",
                      "Environment",
                      "Visibility",
                      ...(isDepartmentAdmin ? ["Requested By"] : []),
                      ...(isSuperAdmin ? ["Department Scope"] : []),
                      "Type",
                      "Status",
                      "Actions",
                    ].map((h) => (
                      <th
                        key={h}
                        className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider"
                      >
                        {t(h)}
                      </th>
                    ))}
                  </tr>
                </thead>

                <tbody className="divide-y">
                  {filteredModels.length === 0 ? (
                    <tr>
                      <td
                        colSpan={8 + (isDepartmentAdmin ? 1 : 0) + (isSuperAdmin ? 1 : 0)}
                        className="px-6 py-12 text-center text-sm text-muted-foreground"
                      >
                        {displayModels.length === 0
                          ? t("No models onboarded yet. Click 'Add Model' to get started.")
                          : t("No models match the current filters.")}
                      </td>
                    </tr>
                  ) : (
                    filteredModels.map((model) => (
                      <tr key={model.id} className="group hover:bg-muted/50">
                        {/* Model Name */}
                        <td className="px-6 py-4">
                          <div className="font-semibold">
                            {model.display_name}
                          </div>
                          {model.description && (
                            <div className="mt-0.5 text-xs text-muted-foreground line-clamp-1">
                              {model.description}
                            </div>
                          )}
                        </td>

                        {/* Provider */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <div className="flex h-8 w-8 items-center justify-center rounded border">
                              {getProviderLogo(model.provider)}
                            </div>
                            <span className="text-sm">
                              {t(getProviderName(model.provider))}
                            </span>
                          </div>
                        </td>

                        {/* Model ID */}
                        <td className="px-6 py-4 text-sm font-mono text-muted-foreground">
                          {model.model_name}
                        </td>

                        {/* Environment */}
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium uppercase ${
                              ENV_BADGE_CLASSES[model.environment] ?? "bg-gray-100 text-gray-700"
                            }`}
                          >
                            {t(ENV_LABELS[model.environment] ?? model.environment)}
                          </span>
                        </td>

                        {/* Visibility */}
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                              VISIBILITY_BADGE_CLASSES[model.visibility_scope ?? "private"] ??
                              "bg-gray-100 text-gray-700"
                            }`}
                          >
                            {t(
                              VISIBILITY_LABELS[model.visibility_scope ?? "private"] ??
                                model.visibility_scope ??
                                "Private",
                            )}
                          </span>
                        </td>

                        {isDepartmentAdmin && (
                          <td className="px-6 py-4 text-sm text-muted-foreground">
                            <div
                              className="max-w-[170px] truncate"
                              title={model.created_by || "-"}
                            >
                              {model.created_by || "-"}
                            </div>
                          </td>
                        )}

                        {isSuperAdmin && (
                          <td className="px-6 py-4 text-sm text-muted-foreground">
                            {(() => {
                              if (model.visibility_scope === "organization") {
                                return "All departments";
                              }
                              if (model.public_dept_ids && model.public_dept_ids.length > 0) {
                                const names = model.public_dept_ids.map((id) => deptById.get(id)?.name ?? id);
                                return names.length > 2
                                  ? `${names.slice(0, 2).join(", ")} +${names.length - 2}`
                                  : names.join(", ");
                              }
                              if (model.dept_id) {
                                const dept = deptById.get(model.dept_id);
                                if (dept) {
                                  return dept.name;
                                }
                                return model.dept_id;
                              }
                              return "-";
                            })()}
                          </td>
                        )}

                        {/* Type */}
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                              model.model_type === "embedding"
                                ? "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400"
                                : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
                            }`}
                          >
                            {model.model_type === "embedding" ? t("Embedding") : t("LLM")}
                          </span>
                        </td>

                        {/* Status */}
                        <td className="px-6 py-4">
                          {model.approval_status === "pending" ? (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-yellow-600">
                              <Clock className="h-3.5 w-3.5" />
                              {t("Pending Approval")}
                            </span>
                          ) : model.approval_status === "rejected" ? (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-red-600">
                              <XCircle className="h-3.5 w-3.5" />
                              {t("Rejected")}
                            </span>
                          ) : model.is_active ? (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-green-600">
                              <CheckCircle className="h-3.5 w-3.5" />
                              {t("Active")}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground">
                              <XCircle className="h-3.5 w-3.5" />
                              {t("Inactive")}
                            </span>
                          )}
                        </td>

                        {/* Actions */}
                        <td className="px-6 py-4">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button className="opacity-0 group-hover:opacity-100 transition-opacity">
                                <MoreVertical className="h-4 w-4" />
                              </button>
                            </DropdownMenuTrigger>

                            <DropdownMenuContent align="end">
                              <DropdownMenuItem
                                onClick={() => {
                                  setSelectedModel(model);
                                  setIsEditModalOpen(true);
                                }}
                              >
                                <Edit2 className="mr-2 h-4 w-4" />
                                {t("Edit")}
                              </DropdownMenuItem>

                              <DropdownMenuSeparator />

                              <DropdownMenuItem
                                className="text-destructive"
                                onClick={() => setDeleteConfirmModel(model)}
                              >
                                <Trash2 className="mr-2 h-4 w-4" />
                                {t("Delete")}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="mt-6 text-center text-sm text-muted-foreground">
              {t("Showing {{shown}} of {{total}} models", {
                shown: filteredModels.length,
                total: displayModels.length,
              })}
            </div>
          </>
        )}
      </div>

      {/* Edit/Create Modal */}
      <EditModelModal
        open={isEditModalOpen}
        onOpenChange={setIsEditModalOpen}
        model={selectedModel}
        modelType={modelTypeFilter}
      />
      <RequestModelModal
        open={isRequestModalOpen}
        onOpenChange={setIsRequestModalOpen}
        modelType={modelTypeFilter}
      />

      {/* Delete Confirmation Dialog */}
      {deleteConfirmModel && (
        <>
          <div
            className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm"
            onClick={() => setDeleteConfirmModel(null)}
          />
          <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-card p-6 shadow-lg">
            <h3 className="text-lg font-semibold">{t("Delete Model")}</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {t("Are you sure you want to delete {{name}}? This action cannot be undone.", {
                name: deleteConfirmModel.display_name,
              })}
            </p>
            <div className="mt-6 flex gap-3">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => setDeleteConfirmModel(null)}
              >
                {t("Cancel")}
              </Button>
              <Button
                variant="destructive"
                className="flex-1"
                onClick={handleDeleteConfirm}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : null}
                {t("Delete")}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
