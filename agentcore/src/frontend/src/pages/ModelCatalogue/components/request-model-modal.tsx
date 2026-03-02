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
import {
  usePostRegistryModel,
  useTestModelConnection,
} from "@/controllers/API/queries/models";
import useAlertStore from "@/stores/alertStore";

interface RequestModelModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface VisibilityOptions {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
}

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "azure", label: "Azure OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "groq", label: "Groq" },
  { value: "openai_compatible", label: "Custom Model" },
];

export default function RequestModelModal({
  open,
  onOpenChange,
}: RequestModelModalProps) {
  const { role } = useContext(AuthContext);
  const normalizedRole = String(role || "").toLowerCase();
  const canMultiDept = normalizedRole === "super_admin" || normalizedRole === "root";
  const isDevBusinessUser =
    normalizedRole === "developer" || normalizedRole === "business_user";

  const [displayName, setDisplayName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [modelName, setModelName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [environment, setEnvironment] = useState<"test" | "uat" | "prod">("test");
  const [visibilityScope, setVisibilityScope] = useState<"private" | "department" | "organization">("private");
  const [deptId, setDeptId] = useState("");
  const [publicDeptIds, setPublicDeptIds] = useState<string[]>([]);
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
  });
  const [chargeCode, setChargeCode] = useState("");
  const [projectName, setProjectName] = useState("");
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const createMutation = usePostRegistryModel();
  const testMutation = useTestModelConnection();
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const isDirectAddPath =
    isDevBusinessUser &&
    environment === "test" &&
    visibilityScope === "private";

  const departmentsForSelectedOrg = useMemo(
    () => visibilityOptions.departments,
    [visibilityOptions.departments],
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

  const resetForm = () => {
    setDisplayName("");
    setProvider("openai");
    setModelName("");
    setBaseUrl("");
    setApiKey("");
    setEnvironment("test");
    setVisibilityScope("private");
    setDeptId("");
    setPublicDeptIds([]);
    setChargeCode("");
    setProjectName("");
    setReason("");
  };

  useEffect(() => {
    if (!open) return;
    api.get("api/mcp/registry/visibility-options").then((res) => {
      const options: VisibilityOptions = res.data || {
        organizations: [],
        departments: [],
      };
      setVisibilityOptions(options);
      if (!deptId) setDeptId(options.departments?.[0]?.id || "");
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (
      (normalizedRole === "developer" || normalizedRole === "department_admin") &&
      visibilityOptions.departments.length > 0
    ) {
      const firstDept = visibilityOptions.departments[0];
      if (!deptId) setDeptId(firstDept.id);
      if (publicDeptIds.length === 0) setPublicDeptIds([firstDept.id]);
    }
  }, [open, normalizedRole, visibilityOptions, deptId, publicDeptIds]);

  const handleClose = () => {
    onOpenChange(false);
    resetForm();
  };

  const handleTestConnection = async () => {
    if (!modelName.trim() || !apiKey.trim()) {
      setErrorData({
        title: "Model Name and API Key are required for test connection.",
      });
      return;
    }
    try {
      const result = await testMutation.mutateAsync({
        provider,
        model_name: modelName,
        base_url: baseUrl || null,
        api_key: apiKey || null,
      });
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) {
      setErrorData({ title: "API Key is required." });
      return;
    }
    if (!chargeCode.trim() || !projectName.trim() || !reason.trim()) {
      setErrorData({ title: "Charge Code, Project Name, and Reason are required." });
      return;
    }
    if (visibilityScope === "department" && !canMultiDept && !deptId) {
      setErrorData({ title: "Department is required for department visibility." });
      return;
    }
    if (visibilityScope === "department" && canMultiDept && publicDeptIds.length === 0) {
      setErrorData({ title: "Select at least one department for department visibility." });
      return;
    }

    const effectiveOrgId =
      visibilityOptions.departments.find((d) => d.id === (canMultiDept ? publicDeptIds[0] : deptId))?.org_id ||
      visibilityOptions.organizations[0]?.id ||
      null;

    setIsSubmitting(true);
    try {
      await createMutation.mutateAsync({
        display_name: displayName,
        description: reason,
        provider,
        model_name: modelName,
        model_type: "llm",
        base_url: baseUrl || null,
        api_key: apiKey || null,
        environment,
        visibility_scope: visibilityScope,
        org_id: visibilityScope === "organization" ? effectiveOrgId : null,
        dept_id: visibilityScope === "department" ? (canMultiDept ? null : deptId || null) : null,
        public_dept_ids: visibilityScope === "department" ? (canMultiDept ? publicDeptIds : deptId ? [deptId] : []) : [],
        provider_config: {
          request_meta: {
            charge_code: chargeCode,
            project_name: projectName,
            reason,
          },
        },
        is_active: true,
      });
      setSuccessData({
        title: isDirectAddPath
          ? "Model added successfully"
          : "Model request submitted successfully",
      });
      handleClose();
    } catch (err: any) {
      setErrorData({
        title: "Failed to submit model action",
        list: [err?.message ?? String(err)],
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-full max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <div className="flex-shrink-0 border-b p-6">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-semibold">Add / Request Model</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Configure the model and submit. DEV + PRIVATE for Developer/Business User is auto-approved.
              </p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 space-y-6 overflow-y-auto p-6">
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Basic Information
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Display Name *</Label>
                <Input
                  required
                  placeholder="e.g., GPT-4.1 for Analytics"
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

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Model Name / ID *</Label>
                <Input
                  required
                  placeholder="e.g., gpt-4.1-mini"
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                />
              </div>
              <div>
                <Label>Base URL</Label>
                <Input
                  placeholder="https://api.example.com/v1"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </div>
            </div>

            <div>
              <Label>API Key *</Label>
              <Input
                type="password"
                required
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                Required for add/request. Test connection is recommended before submitting.
              </p>
            </div>

            <div>
              <Label>Environment *</Label>
              <div className="mt-2 flex gap-2">
                {[
                  { value: "test", label: "DEV" },
                  { value: "uat", label: "UAT" },
                  { value: "prod", label: "PROD" },
                ].map((env) => (
                  <button
                    key={env.value}
                    type="button"
                    onClick={() => setEnvironment(env.value as "test" | "uat" | "prod")}
                    className={`rounded-md border px-3 py-2 text-sm ${
                      environment === env.value
                        ? "border-[var(--button-primary)] bg-[var(--button-primary)] text-[var(--button-primary-foreground)]"
                        : "border-input bg-background"
                    }`}
                  >
                    {env.label}
                  </button>
                ))}
              </div>
            </div>
          </fieldset>

          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Tenancy
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Visibility Scope *</Label>
                <select
                  value={visibilityScope}
                  onChange={(e) =>
                    setVisibilityScope(
                      e.target.value as "private" | "department" | "organization",
                    )
                  }
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="private">private</option>
                  <option value="department">department</option>
                  <option value="organization">organization</option>
                </select>
              </div>

              {visibilityScope === "department" ? (
                <div>
                  <Label>{canMultiDept ? "Departments *" : "Department *"}</Label>
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
                      disabled={
                        normalizedRole === "developer" ||
                        normalizedRole === "department_admin"
                      }
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
                <div className="flex items-end text-xs text-muted-foreground">
                  Organization is derived automatically from your tenancy scope.
                </div>
              )}
            </div>
          </fieldset>

          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Request Details
            </legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Charge Code *</Label>
                <Input
                  required
                  placeholder="e.g., CC-1042"
                  value={chargeCode}
                  onChange={(e) => setChargeCode(e.target.value)}
                />
              </div>
              <div>
                <Label>Project Name *</Label>
                <Input
                  required
                  placeholder="e.g., Customer Support Revamp"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                />
              </div>
            </div>

            <div>
              <Label>Reason *</Label>
              <Textarea
                required
                rows={4}
                placeholder="Tell admins why this model is needed and expected use-case."
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
          </fieldset>
        </form>

        <div className="flex-shrink-0 border-t p-6">
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={handleTestConnection}
              disabled={testMutation.isPending || !modelName || !apiKey}
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
              onClick={handleSubmit}
              disabled={isSubmitting || createMutation.isPending}
            >
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isDirectAddPath ? "Add Model" : "Submit Request"}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {isDirectAddPath
              ? "This will be auto-approved as DEV + PRIVATE."
              : "This will create an approval request based on environment and visibility."}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
