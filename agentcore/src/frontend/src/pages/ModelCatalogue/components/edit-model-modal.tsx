import { useContext, useEffect, useMemo, useState } from "react";
import { ChevronDown, Loader2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import type {
  ModelType,
  ModelTypeFilter,
  ModelCreateRequest,
  ModelUpdateRequest,
  ModelEnvironment,
} from "@/types/models/models";
import useAlertStore from "@/stores/alertStore";
import {
  usePostRegistryModel,
  usePutRegistryModel,
  useTestModelConnection,
  usePromoteRegistryModel,
  useChangeModelVisibility,
} from "@/controllers/API/queries/models";

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "azure", label: "Azure" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "groq", label: "Groq" },
  { value: "openai_compatible", label: "Custom Model" },
];

const DEFAULT_AZURE_API_VERSION = "2025-10-01-preview";

const ENVIRONMENTS: { value: ModelEnvironment; label: string }[] = [
  { value: "test", label: "DEV" },
  { value: "uat", label: "UAT" },
  { value: "prod", label: "PROD" },
];

type VisibilityOptions = {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
};

interface EditModelModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  model?: ModelType | null;
  modelType?: ModelTypeFilter;
}

export default function EditModelModal({
  open,
  onOpenChange,
  model,
  modelType = "llm",
}: EditModelModalProps) {
  const { role } = useContext(AuthContext);
  const normalizedRole = String(role || "").toLowerCase();
  const canMultiDept = normalizedRole === "super_admin" || normalizedRole === "root";
  const isEditMode = !!model;

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const createMutation = usePostRegistryModel();
  const updateMutation = usePutRegistryModel();
  const testMutation = useTestModelConnection();
  const promoteMutation = usePromoteRegistryModel();
  const visibilityMutation = useChangeModelVisibility();

  /* ---------------------------------- Form State ---------------------------------- */

  const [displayName, setDisplayName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [modelName, setModelName] = useState("");
  const [description, setDescription] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [environment, setEnvironment] = useState<ModelEnvironment>("test");
  const [visibilityScope, setVisibilityScope] = useState<"private" | "department" | "organization">("private");
  const [orgId, setOrgId] = useState("");
  const [deptId, setDeptId] = useState("");
  const [publicDeptIds, setPublicDeptIds] = useState<string[]>([]);
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
  });
  const [isActive, setIsActive] = useState(true);

  // Provider-specific
  const [azureDeployment, setAzureDeployment] = useState("");
  const [azureApiVersion, setAzureApiVersion] = useState(DEFAULT_AZURE_API_VERSION);
  const [customHeaders, setCustomHeaders] = useState("");

  // Default params (LLM)
  const [temperature, setTemperature] = useState<number | "">("");
  const [maxTokens, setMaxTokens] = useState<number | "">("");

  // Embedding-specific
  const [dimensions, setDimensions] = useState<number | "">("");

  const departmentsForSelectedOrg = useMemo(
    () => visibilityOptions.departments.filter((d) => !orgId || d.org_id === orgId),
    [visibilityOptions.departments, orgId],
  );
  const selectedDeptLabel = useMemo(() => {
    if (publicDeptIds.length === 0) return "Select departments";
    const names = departmentsForSelectedOrg
      .filter((dept) => publicDeptIds.includes(dept.id))
      .map((dept) => dept.name);
    if (names.length === 0) return "Select departments";
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  }, [departmentsForSelectedOrg, publicDeptIds]);

  /* ---------------------------------- Populate form on edit ---------------------------------- */

  useEffect(() => {
    if (!open) return;

    if (model) {
      setDisplayName(model.display_name);
      setProvider(model.provider);
      setModelName(model.model_name);
      setDescription(model.description ?? "");
      setApiKey(""); // never pre-fill
      setBaseUrl(model.base_url ?? "");
      setEnvironment(model.environment ?? "test");
      setVisibilityScope(model.visibility_scope ?? "private");
      setOrgId(model.org_id ?? "");
      setDeptId(model.dept_id ?? "");
      setPublicDeptIds(
        model.public_dept_ids && model.public_dept_ids.length > 0
          ? model.public_dept_ids
          : model.dept_id
            ? [model.dept_id]
            : [],
      );
      setIsActive(model.is_active);

      const pc = model.provider_config ?? {};
      setAzureDeployment(pc.azure_deployment ?? "");
      setAzureApiVersion(pc.api_version ?? DEFAULT_AZURE_API_VERSION);
      setCustomHeaders(pc.custom_headers ? JSON.stringify(pc.custom_headers, null, 2) : "");

      const dp = model.default_params ?? {};
      setTemperature(dp.temperature ?? 0.7);
      setMaxTokens(dp.max_tokens ?? "");
      setDimensions(dp.dimensions ?? "");
    } else {
      // Reset for create
      setDisplayName("");
      setProvider("openai");
      setModelName("");
      setDescription("");
      setApiKey("");
      setBaseUrl("");
      setEnvironment("test");
      setVisibilityScope("private");
      setOrgId("");
      setDeptId("");
      setPublicDeptIds([]);
      setIsActive(true);
      setAzureDeployment("");
      setAzureApiVersion(DEFAULT_AZURE_API_VERSION);
      setCustomHeaders("");
      setTemperature(0.7);
      setMaxTokens("");
      setDimensions("");
    }
  }, [model, open]);

  useEffect(() => {
    if (!open) return;
    api.get("api/mcp/registry/visibility-options").then((res) => {
      const options: VisibilityOptions = res.data || {
        organizations: [],
        departments: [],
      };
      setVisibilityOptions(options);
      if (!orgId) setOrgId(options.organizations?.[0]?.id || "");
      if (!deptId) setDeptId(options.departments?.[0]?.id || "");
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if ((normalizedRole === "developer" || normalizedRole === "department_admin") && visibilityOptions.departments.length > 0) {
      const firstDept = visibilityOptions.departments[0];
      if (!deptId) setDeptId(firstDept.id);
      if (!orgId) setOrgId(firstDept.org_id);
      if (publicDeptIds.length === 0) setPublicDeptIds([firstDept.id]);
    }
  }, [open, normalizedRole, visibilityOptions, deptId, orgId, publicDeptIds]);

  /* ---------------------------------- Build payload ---------------------------------- */

  const buildProviderConfig = (): Record<string, any> | undefined => {
    const config: Record<string, any> = {};
    if (provider === "azure") {
      if (azureDeployment) config.azure_deployment = azureDeployment;
      if (azureApiVersion) config.api_version = azureApiVersion;
    }
    if (provider === "openai_compatible" && customHeaders) {
      try {
        config.custom_headers = JSON.parse(customHeaders);
      } catch {
        /* ignore parse errors */
      }
    }
    return Object.keys(config).length ? config : undefined;
  };

  const isEmbedding = modelType === "embedding" || model?.model_type === "embedding";

  const buildDefaultParams = () => {
    const params: Record<string, any> = {};
    if (!isEmbedding) {
      if (temperature !== "") params.temperature = Number(temperature);
      if (maxTokens !== "") params.max_tokens = Number(maxTokens);
    }
    if (isEmbedding && dimensions !== "") {
      params.dimensions = Number(dimensions);
    }
    return Object.keys(params).length ? params : undefined;
  };

  /* ---------------------------------- Handlers ---------------------------------- */

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      if (isEditMode && model) {
        const originalEnvironment = model.environment ?? "test";
        const originalVisibility = model.visibility_scope ?? "private";

        const payload: ModelUpdateRequest = {
          display_name: displayName,
          description: description || null,
          provider,
          model_name: modelName,
          model_type: isEmbedding ? "embedding" : "llm",
          base_url: baseUrl || null,
          org_id: visibilityScope === "private" ? null : orgId || null,
          dept_id: visibilityScope === "department" ? (canMultiDept ? null : deptId || null) : null,
          public_dept_ids:
            visibilityScope === "department"
              ? (canMultiDept ? publicDeptIds : deptId ? [deptId] : [])
              : [],
          provider_config: buildProviderConfig() ?? null,
          default_params: buildDefaultParams() ?? null,
          is_active: isActive,
        };
        if (apiKey) payload.api_key = apiKey;

        await updateMutation.mutateAsync({ id: model.id, data: payload });

        if (environment !== originalEnvironment) {
          await promoteMutation.mutateAsync({
            id: model.id,
            target_environment: environment,
          });
        }

        if (visibilityScope !== originalVisibility) {
          await visibilityMutation.mutateAsync({
            id: model.id,
            visibility_scope: visibilityScope,
          });
        }

        setSuccessData({
          title:
            environment !== originalEnvironment || visibilityScope !== originalVisibility
              ? `Model "${displayName}" updated. Related approval request(s) submitted.`
              : `Model "${displayName}" updated.`,
        });
      } else {
        const payload: ModelCreateRequest = {
          display_name: displayName,
          description: description || null,
          provider,
          model_name: modelName,
          model_type: isEmbedding ? "embedding" : "llm",
          base_url: baseUrl || null,
          api_key: apiKey || null,
          environment,
          visibility_scope: visibilityScope,
          org_id: visibilityScope === "organization" ? orgId || null : null,
          dept_id: visibilityScope === "department" ? (canMultiDept ? null : deptId || null) : null,
          public_dept_ids:
            visibilityScope === "department"
              ? (canMultiDept ? publicDeptIds : deptId ? [deptId] : [])
              : [],
          provider_config: buildProviderConfig() ?? null,
          default_params: buildDefaultParams() ?? null,
          is_active: isActive,
        };

        await createMutation.mutateAsync(payload);
        setSuccessData({ title: `${isEmbedding ? "Embedding" : "Model"} "${displayName}" added to ${environment} environment.` });
      }
      onOpenChange(false);
    } catch (err: any) {
      setErrorData({
        title: isEditMode ? "Failed to update model" : "Failed to create model",
        list: [err?.message ?? String(err)],
      });
    }
  };

  const handleTestConnection = async () => {
    try {
      const testPayload = {
        provider,
        model_name: modelName,
        base_url: baseUrl || null,
        api_key: apiKey || null,
        provider_config: buildProviderConfig() ?? null,
        isEmbedding,
      };
      const result = await testMutation.mutateAsync(testPayload);
      if (result.success) {
        setSuccessData({
          title: `Connection successful${result.latency_ms ? ` (${result.latency_ms}ms)` : ""}`,
        });
      } else {
        setErrorData({ title: "Connection failed", list: [result.message] });
      }
    } catch (err: any) {
      setErrorData({
        title: "Test connection error",
        list: [err?.message ?? String(err)],
      });
    }
  };

  const handleClose = () => onOpenChange(false);

  const isSaving =
    createMutation.isPending ||
    updateMutation.isPending ||
    promoteMutation.isPending ||
    visibilityMutation.isPending;
  const canTest = !!modelName && !!apiKey;

  if (!open) return null;

  /* ---------------------------------- JSX ---------------------------------- */

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-full max-w-2xl flex-col gap-0 overflow-hidden p-0">
        {/* Header */}
        <div className="flex-shrink-0 border-b p-6">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-semibold">
                {isEditMode
                  ? isEmbedding ? "Edit Embedding Model" : "Edit Model"
                  : isEmbedding ? "Add Embedding Model" : "Add Model"}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {isEditMode
                  ? isEmbedding ? "Update embedding model configuration" : "Update model configuration and settings"
                  : isEmbedding ? "Onboard a new embedding model to the registry" : "Onboard a new AI model to the registry"}
              </p>
            </div>
          </div>
        </div>

        {/* Scrollable Form Body */}
        <form
          onSubmit={handleSubmit}
          className="flex-1 overflow-y-auto p-6 space-y-6"
        >
          {/* ========== BASIC INFO ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Basic Information
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Display Name *</Label>
                <Input
                  required
                  placeholder="e.g., GPT-4o PROD"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                />
              </div>
              <div>
                <Label>Provider *</Label>
                <select
                  required
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <Label>Description</Label>
              <Textarea
                rows={2}
                placeholder="Brief description of this model configuration"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </fieldset>

          {/* ========== CONNECTION ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Connection
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Model Name / ID *</Label>
                <Input
                  required
                  placeholder="e.g., gpt-4o, claude-3-opus-20240229"
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                />
              </div>
              <div>
                <Label>API Key {!isEditMode && "*"}</Label>
                <Input
                  type="password"
                  required={!isEditMode}
                  placeholder={isEditMode ? "(unchanged)" : "sk-..."}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Encrypted before storage. Never exposed in responses.
                </p>
              </div>
            </div>

            <div>
              <Label>
                Base URL
                {(provider === "azure" || provider === "openai_compatible") &&
                  " *"}
              </Label>
              <Input
                required={
                  provider === "azure" || provider === "openai_compatible"
                }
                placeholder={
                  provider === "azure"
                    ? "https://your-resource.openai.azure.com/"
                    : "https://api.example.com/v1"
                }
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>

            {/* Azure-specific */}
            {provider === "azure" && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Deployment Name *</Label>
                  <Input
                    required
                    placeholder="my-gpt4-deployment"
                    value={azureDeployment}
                    onChange={(e) => setAzureDeployment(e.target.value)}
                  />
                </div>
                <div>
                  <Label>API Version</Label>
                  <Input
                    placeholder="2025-10-01-preview"
                    value={azureApiVersion}
                    onChange={(e) => setAzureApiVersion(e.target.value)}
                  />
                </div>
              </div>
            )}

            {/* Custom headers */}
            {provider === "openai_compatible" && (
              <div>
                <Label>Custom Headers (JSON)</Label>
                <Textarea
                  rows={3}
                  placeholder='{"X-Custom-Header": "value"}'
                  value={customHeaders}
                  onChange={(e) => setCustomHeaders(e.target.value)}
                />
              </div>
            )}
          </fieldset>

          {/* ========== ENVIRONMENT ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Environment & Tenancy
            </legend>
            <div className="flex gap-3">
              {ENVIRONMENTS.map((env) => (
                <button
                  key={env.value}
                  type="button"
                  onClick={() => setEnvironment(env.value)}
                  className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                    environment === env.value
                      ? "border-[var(--button-primary)] bg-[var(--button-primary)] text-[var(--button-primary-foreground)]"
                      : "border-input bg-background hover:bg-muted"
                  }`}
                >
                  {env.label}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {isEditMode
                ? "Changing environment here will submit a promotion request when applicable."
                : <>Models default to <strong>DEV</strong>. Promote to UAT or <strong>PROD</strong> when ready.</>}
            </p>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Visibility Scope</Label>
                <select
                  value={visibilityScope}
                  onChange={(e) =>
                    setVisibilityScope(e.target.value as "private" | "department" | "organization")
                  }
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="private">private</option>
                  <option value="department">department</option>
                  <option value="organization">organization</option>
                </select>
              </div>
              {visibilityScope === "organization" ? (
                <div>
                  <Label>Organization</Label>
                  <select
                    value={orgId}
                    onChange={(e) => setOrgId(e.target.value)}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    disabled={normalizedRole === "developer" || normalizedRole === "department_admin"}
                  >
                    <option value="">Select organization</option>
                    {visibilityOptions.organizations.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                </div>
              ) : visibilityScope === "department" ? (
                <div>
                  <Label>{canMultiDept ? "Departments" : "Department"}</Label>
                  {canMultiDept ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="outline"
                          className="w-full justify-between font-normal"
                        >
                          <span className="truncate text-left">{selectedDeptLabel}</span>
                          <ChevronDown className="ml-2 h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="start" className="max-h-64 w-[340px] overflow-auto">
                        {departmentsForSelectedOrg.map((dept) => (
                          <DropdownMenuCheckboxItem
                            key={dept.id}
                            checked={publicDeptIds.includes(dept.id)}
                            onSelect={(event) => event.preventDefault()}
                            onCheckedChange={(checked) => {
                              setPublicDeptIds((prev) =>
                                checked
                                  ? Array.from(new Set([...prev, dept.id]))
                                  : prev.filter((id) => id !== dept.id),
                              );
                            }}
                          >
                            {dept.name}
                          </DropdownMenuCheckboxItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : (
                    <select
                      value={deptId}
                      onChange={(e) => setDeptId(e.target.value)}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      disabled={normalizedRole === "developer" || normalizedRole === "department_admin"}
                    >
                      <option value="">Select department</option>
                      {departmentsForSelectedOrg.map((dept) => (
                        <option key={dept.id} value={dept.id}>
                          {dept.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              ) : (
                <div />
              )}
            </div>
            {isEditMode && (
              <p className="text-[11px] text-muted-foreground">
                Visibility changes here will submit approval requests when required.
              </p>
            )}
          </fieldset>

          {/* ========== DEFAULT PARAMS ========== */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {isEmbedding ? "Embedding Parameters" : "Default Parameters"}
            </legend>

            <div className="grid grid-cols-2 gap-4">
              {!isEmbedding && (
                <>
                  <div>
                    <Label>Temperature (0-2)</Label>
                    <Input
                      type="number"
                      step="0.01"
                      min="0"
                      max="2"
                      placeholder="Optional"
                      value={temperature}
                      onChange={(e) =>
                        setTemperature(
                          e.target.value ? Number(e.target.value) : "",
                        )
                      }
                    />
                  </div>
                  <div>
                    <Label>Max Output Tokens</Label>
                    <Input
                      type="number"
                      placeholder="4096"
                      value={maxTokens}
                      onChange={(e) =>
                        setMaxTokens(e.target.value ? Number(e.target.value) : "")
                      }
                    />
                  </div>
                </>
              )}
              {isEmbedding && (
                <div>
                  <Label>Dimensions</Label>
                  <Input
                    type="number"
                    placeholder="e.g., 1536"
                    value={dimensions}
                    onChange={(e) =>
                      setDimensions(e.target.value ? Number(e.target.value) : "")
                    }
                  />
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Leave empty to use the model's default dimension.
                  </p>
                </div>
              )}
            </div>
          </fieldset>

          {/* ========== STATUS ========== */}
          <fieldset className="space-y-2">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Status
            </legend>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              Active
            </label>
            <p className="text-[11px] text-muted-foreground">
              Inactive models won't appear in the agent builder component
              dropdown.
            </p>
          </fieldset>
        </form>

        {/* Footer */}
        <div className="flex-shrink-0 border-t p-6">
          <div className="flex items-center gap-3">
            {/* Test Connection */}
            <Button
              type="button"
              variant="outline"
              disabled={!canTest || testMutation.isPending}
              onClick={handleTestConnection}
            >
              {testMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Zap className="mr-2 h-4 w-4" />
              )}
              Test Connection
            </Button>

            <div className="flex-1" />

            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isSaving}
              onClick={handleSubmit}
            >
              {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isEditMode ? "Save Changes" : isEmbedding ? "Add Embedding" : "Add Model"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
