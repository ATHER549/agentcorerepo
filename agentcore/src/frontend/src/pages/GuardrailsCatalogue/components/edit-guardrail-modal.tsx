import { Loader2 } from "lucide-react";
import { useContext, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  type GuardrailCreateOrUpdatePayload,
  type GuardrailInfo,
  usePatchGuardrailCatalogue,
  usePostGuardrailCatalogue,
} from "@/controllers/API/queries/guardrails";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useNameAvailability } from "@/controllers/API/queries/common/use-name-availability";
import { useGetRegistryModels } from "@/controllers/API/queries/models";
import { AuthContext } from "@/contexts/authContext";
import useAlertStore from "@/stores/alertStore";

interface EditGuardrailModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  guardrail?: GuardrailInfo | null;
  frameworkId?: "nemo" | "arize";
}

const CATEGORY_OPTIONS = [
  "content-safety",
  "jailbreak",
  "topic-control",
  "pii-detection",
];

const getConfigTemplate = (): string => {
  return `# models section is auto-injected from Model Registry
rails:
  input:
    flows:
      - self check input`;
};

const getPromptsTemplate = (): string => {
  return `prompts:
  - task: self_check_input
    content: |
      You are a safety classifier for user input.

      Block the message if it requests harmful, illegal, abusive, or violent guidance.

      User message: "{{ user_input }}"

      Should this message be blocked?
      Answer only Yes or No.
      Answer:`;
};

const pickFirstString = (
  runtimeConfig: GuardrailInfo["runtimeConfig"],
  keys: string[],
): string => {
  if (!runtimeConfig) return "";
  for (const key of keys) {
    const value = (runtimeConfig as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
  }
  return "";
};

export default function EditGuardrailModal({
  open,
  onOpenChange,
  guardrail,
  frameworkId = "nemo",
}: EditGuardrailModalProps) {
  const isEditMode = !!guardrail;
  const { role } = useContext(AuthContext);
  const createMutation = usePostGuardrailCatalogue();
  const updateMutation = usePatchGuardrailCatalogue();

  const { data: registryModels = [], isLoading: isModelsLoading } =
    useGetRegistryModels({
      active_only: false,
    });

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [modelRegistryId, setModelRegistryId] = useState("");
  const [category, setCategory] = useState("content-safety");
  const [status, setStatus] = useState<"active" | "inactive">("active");
  const [isCustom, setIsCustom] = useState(false);

  const [configYml, setConfigYml] = useState("");
  const [promptsYml, setPromptsYml] = useState("");
  const [railsCo, setRailsCo] = useState("");
  const [preservedFiles, setPreservedFiles] = useState<Record<string, string>>();
  const [visibility, setVisibility] = useState<"private" | "public">("private");
  const [publicScope, setPublicScope] = useState<"organization" | "department">("department");
  const [orgId, setOrgId] = useState("");
  const [deptId, setDeptId] = useState("");
  const [publicDeptIds, setPublicDeptIds] = useState<string[]>([]);
  const [sharedUserEmails, setSharedUserEmails] = useState<string[]>([]);
  const [visibilityOptions, setVisibilityOptions] = useState<{
    organizations: { id: string; name: string }[];
    departments: { id: string; name: string; org_id: string }[];
    private_share_users: { id: string; email: string }[];
  }>({ organizations: [], departments: [], private_share_users: [] });

  const selectedModel = useMemo(
    () => registryModels.find((model) => model.id === modelRegistryId) ?? null,
    [registryModels, modelRegistryId],
  );

  const defaultModelId = useMemo(() => {
    const activeModel = registryModels.find((model) => model.is_active);
    return (activeModel ?? registryModels[0])?.id ?? "";
  }, [registryModels]);

  useEffect(() => {
    if (!open) return;

    if (guardrail) {
      setName(guardrail.name ?? "");
      setDescription(guardrail.description ?? "");
      setModelRegistryId(guardrail.modelRegistryId ?? "");
      setCategory(guardrail.category ?? "content-safety");
      setStatus((guardrail.status ?? "active") as "active" | "inactive");
      setIsCustom(Boolean(guardrail.isCustom));

      const runtimeConfig = guardrail.runtimeConfig ?? undefined;
      setConfigYml(
        pickFirstString(runtimeConfig, [
          "config_yml",
          "configYml",
          "config.yml",
        ]),
      );
      setRailsCo(
        pickFirstString(runtimeConfig, ["rails_co", "railsCo", "rails.co"]),
      );
      setPromptsYml(
        pickFirstString(runtimeConfig, [
          "prompts_yml",
          "promptsYml",
          "prompts.yml",
        ]),
      );
      const files = runtimeConfig?.files;
      if (files && typeof files === "object" && !Array.isArray(files)) {
        const safeFiles = Object.fromEntries(
          Object.entries(files).filter(
            ([key, value]) => typeof key === "string" && typeof value === "string",
          ),
        ) as Record<string, string>;
        setPreservedFiles(Object.keys(safeFiles).length > 0 ? safeFiles : undefined);
      } else {
        setPreservedFiles(undefined);
      }
      return;
    }

    // For new guardrails, default to first active model
    if (registryModels.length > 0) {
      setName("");
      setDescription("");
      setModelRegistryId(defaultModelId);
      setCategory("content-safety");
      setStatus("active");
      setIsCustom(false);
      setConfigYml(getConfigTemplate());
      setPromptsYml(getPromptsTemplate());
      setRailsCo("");
      setPreservedFiles(undefined);
    }
  }, [guardrail, open, registryModels, defaultModelId]);

  useEffect(() => {
    if (!open) return;
    api.get(`${getURL("GUARDRAILS_CATALOGUE")}/visibility-options`).then((res) => {
      const options = res.data || {
        organizations: [],
        departments: [],
        private_share_users: [],
      };
      setVisibilityOptions(options);
      if (!isEditMode) {
        const firstOrg = options.organizations?.[0]?.id || "";
        const firstDept = options.departments?.[0]?.id || "";
        setOrgId((prev) => prev || firstOrg);
        setDeptId((prev) => prev || firstDept);
      }
    });
  }, [open, isEditMode]);

  useEffect(() => {
    if (!open) return;
    if (guardrail) {
      setVisibility((guardrail.visibility as "private" | "public") || "private");
      setPublicScope((guardrail.public_scope as "organization" | "department") || "department");
      setOrgId(guardrail.org_id || "");
      setDeptId(guardrail.dept_id || "");
      setPublicDeptIds(guardrail.public_dept_ids || []);
      setSharedUserEmails([]);
    } else {
      setVisibility("private");
      setPublicScope("department");
      setPublicDeptIds([]);
      setSharedUserEmails([]);
    }
  }, [guardrail, open]);

  useEffect(() => {
    if (!open || visibility !== "public") return;
    const canMultiDept = role === "super_admin" || role === "root";

    if (publicScope === "organization") {
      if ((role === "developer" || role === "department_admin") && !orgId && visibilityOptions.organizations.length > 0) {
        setOrgId(visibilityOptions.organizations[0].id);
      }
      return;
    }

    if (!canMultiDept && !deptId && visibilityOptions.departments.length > 0) {
      const firstDept = visibilityOptions.departments[0];
      setDeptId(firstDept.id);
      setOrgId((prev) => prev || firstDept.org_id);
    }
  }, [
    open,
    visibility,
    publicScope,
    role,
    orgId,
    deptId,
    visibilityOptions.organizations,
    visibilityOptions.departments,
  ]);

  const isSaving = createMutation.isPending || updateMutation.isPending;
  const effectiveNameScope = useMemo(() => {
    let effectiveOrgId: string | null = orgId || null;
    let effectiveDeptId: string | null = deptId || null;
    const canMultiDept = role === "super_admin" || role === "root";

    if (visibility === "public") {
      if (publicScope === "organization") {
        effectiveDeptId = null;
      } else if (publicScope === "department") {
        if (canMultiDept) {
          effectiveDeptId = publicDeptIds.length === 1 ? publicDeptIds[0] : null;
        }
        if (!effectiveOrgId) {
          const selectedDept =
            visibilityOptions.departments.find((d) => d.id === effectiveDeptId) ||
            visibilityOptions.departments[0];
          effectiveOrgId = selectedDept?.org_id || null;
        }
      }
    } else if (role === "developer" || role === "department_admin") {
      const defaultDept = visibilityOptions.departments[0];
      if (defaultDept) {
        effectiveOrgId = effectiveOrgId || defaultDept.org_id;
        effectiveDeptId = effectiveDeptId || defaultDept.id;
      }
    }

    return { org_id: effectiveOrgId, dept_id: effectiveDeptId };
  }, [
    visibility,
    publicScope,
    publicDeptIds,
    orgId,
    deptId,
    role,
    visibilityOptions.departments,
  ]);
  const guardrailNameAvailability = useNameAvailability({
    entity: "guardrail",
    name,
    org_id: effectiveNameScope.org_id,
    dept_id: effectiveNameScope.dept_id,
    exclude_id: guardrail?.id ?? null,
    enabled: open && name.trim().length > 0,
  });
  const isVisibilityInvalid =
    visibility === "public" &&
    (
      (publicScope === "organization" && !orgId) ||
      (publicScope === "department" &&
        ((role === "super_admin" || role === "root")
          ? publicDeptIds.length === 0
          : !deptId))
    );

  const buildRuntimeConfig =
    (): GuardrailCreateOrUpdatePayload["runtimeConfig"] => {
      const normalizedConfigYml = configYml.trim();
      const normalizedPromptsYml = promptsYml.trim();
      const normalizedRailsCo = railsCo.trim();
      const parsedExtraFiles =
        preservedFiles && Object.keys(preservedFiles).length > 0
          ? preservedFiles
          : undefined;

      const hasAnyRuntimeConfig =
        normalizedConfigYml !== "" ||
        normalizedPromptsYml !== "" ||
        normalizedRailsCo !== "" ||
        Boolean(parsedExtraFiles);

      if (!hasAnyRuntimeConfig) {
        return null;
      }

      return {
        config_yml: normalizedConfigYml || undefined,
        rails_co: normalizedRailsCo || undefined,
        prompts_yml: normalizedPromptsYml || undefined,
        files: parsedExtraFiles,
      };
    };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (guardrailNameAvailability.isNameTaken) {
      setErrorData({
        title: "Name already taken",
        list: [guardrailNameAvailability.reason || "Please choose a different name."],
      });
      return;
    }

    if (!modelRegistryId) {
      setErrorData({
        title: "Model is required",
        list: ["Please select a model from Model Registry."],
      });
      return;
    }

    if (status === "active" && configYml.trim() === "") {
      setErrorData({
        title: "config_yml is required",
        list: ["Active guardrails require config_yml. prompts_yml is optional."],
      });
      return;
    }

    let runtimeConfig: GuardrailCreateOrUpdatePayload["runtimeConfig"] = null;
    try {
      runtimeConfig = buildRuntimeConfig();
    } catch (error) {
      setErrorData({ title: "Invalid runtime config", list: [String(error)] });
      return;
    }

    const payload: GuardrailCreateOrUpdatePayload = {
      name: name.trim(),
      description: description.trim() || null,
      framework: (guardrail?.framework as "nemo" | "arize" | undefined) || frameworkId,
      modelRegistryId,
      category,
      status,
      isCustom,
      runtimeConfig,
      org_id: orgId || null,
      dept_id: deptId || null,
      visibility,
      public_scope: visibility === "public" ? publicScope : null,
      public_dept_ids: visibility === "public" && publicScope === "department" ? publicDeptIds : [],
      shared_user_emails:
        role === "department_admin" && visibility === "private" ? sharedUserEmails : [],
    };

    try {
      if (isEditMode && guardrail?.id) {
        await updateMutation.mutateAsync({ id: guardrail.id, payload });
        setSuccessData({ title: `Guardrail "${payload.name}" updated.` });
      } else {
        await createMutation.mutateAsync(payload);
        setSuccessData({ title: `Guardrail "${payload.name}" created.` });
      }
      onOpenChange(false);
    } catch (error) {
      setErrorData({
        title: isEditMode
          ? "Failed to update guardrail"
          : "Failed to create guardrail",
        list: [String(error)],
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? "Edit Guardrail" : "Add Guardrail"}
          </DialogTitle>
          <DialogDescription>
            Configure guardrail metadata and NeMo runtime files. You only need
            `config_yml` and optional `prompts_yml`. Model details and
            credentials come from Model Registry.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="guardrail-name">Name *</Label>
              <Input
                id="guardrail-name"
                required
                placeholder="NeMo Content Safety"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              {name.trim().length > 0 &&
                !guardrailNameAvailability.isFetching &&
                guardrailNameAvailability.isNameTaken && (
                  <p className="text-xs font-medium text-red-500">
                    {guardrailNameAvailability.reason ??
                      "This name is already taken in the selected scope."}
                  </p>
                )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="guardrail-model">Model Registry Entry *</Label>
              <select
                id="guardrail-model"
                required
                value={modelRegistryId}
                onChange={(event) => setModelRegistryId(event.target.value)}
                disabled={isModelsLoading || registryModels.length === 0}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                {registryModels.length === 0 ? (
                  <option value="">
                    {isModelsLoading
                      ? "Loading models..."
                      : "No models in registry"}
                  </option>
                ) : (
                  <>
                    <option value="" disabled>
                      Select a model
                    </option>
                    {registryModels.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.display_name} ({option.provider}/
                        {option.model_name}){option.is_active ? "" : " [inactive]"}
                      </option>
                    ))}
                  </>
                )}
              </select>
              {selectedModel && (
                <p className="text-xs text-muted-foreground">
                  Provider:{" "}
                  <span className="font-medium">{selectedModel.provider}</span>{" "}
                  | Model:{" "}
                  <span className="font-medium">
                    {selectedModel.model_name}
                  </span>
                </p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="guardrail-description">Description</Label>
            <Textarea
              id="guardrail-description"
              rows={2}
              placeholder="What this guardrail enforces"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Visibility</Label>
              <select
                value={visibility}
                onChange={(event) =>
                  setVisibility(event.target.value as "private" | "public")
                }
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="private">private</option>
                <option value="public">public</option>
              </select>
            </div>
            {visibility === "public" && (
              <div className="space-y-1.5">
                <Label>Public Scope</Label>
                <select
                  value={publicScope}
                  onChange={(event) =>
                    setPublicScope(event.target.value as "organization" | "department")
                  }
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="organization">organization</option>
                  <option value="department">department</option>
                </select>
              </div>
            )}
          </div>

          {visibility === "public" && publicScope === "organization" && (
            <div className="space-y-1.5">
              <Label>Organization</Label>
              <select
                value={orgId}
                onChange={(event) => setOrgId(event.target.value)}
                disabled={role === "developer" || role === "department_admin"}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-80"
              >
                {visibilityOptions.organizations.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {visibility === "public" && publicScope === "department" && (
            <div className="space-y-1.5">
              <Label>Department{role === "super_admin" || role === "root" ? "s" : ""}</Label>
              {role === "super_admin" || role === "root" ? (
                <select
                  multiple
                  value={publicDeptIds}
                  onChange={(event) =>
                    setPublicDeptIds(
                      Array.from(event.target.selectedOptions).map((o) => o.value),
                    )
                  }
                  className="min-h-[84px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  {visibilityOptions.departments
                    .filter((d) => !orgId || d.org_id === orgId)
                    .map((dept) => (
                      <option key={dept.id} value={dept.id}>
                        {dept.name}
                      </option>
                    ))}
                </select>
              ) : (
                <select
                  value={deptId}
                  disabled
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-80"
                >
                  {visibilityOptions.departments.map((dept) => (
                    <option key={dept.id} value={dept.id}>
                      {dept.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {visibility === "private" && role === "department_admin" && (
            <div className="space-y-1.5">
              <Label>Additional Users (optional)</Label>
              <select
                multiple
                value={sharedUserEmails}
                onChange={(event) =>
                  setSharedUserEmails(
                    Array.from(event.target.selectedOptions).map((o) => o.value),
                  )
                }
                className="min-h-[84px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                {visibilityOptions.private_share_users.map((u) => (
                  <option key={u.id} value={u.email}>
                    {u.email}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="space-y-1.5 md:col-span-2">
              <Label htmlFor="guardrail-category">Category *</Label>
              <select
                id="guardrail-category"
                required
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="guardrail-status">Status *</Label>
              <select
                id="guardrail-status"
                required
                value={status}
                onChange={(event) =>
                  setStatus(event.target.value as "active" | "inactive")
                }
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="active">active</option>
                <option value="inactive">inactive</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-2 text-sm">
            <input
              id="guardrail-custom"
              type="checkbox"
              checked={isCustom}
              onChange={(event) => setIsCustom(event.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <Label htmlFor="guardrail-custom" className="text-sm">
              Mark as custom guardrail
            </Label>
          </div>

          <div className="space-y-3 rounded-md border p-4">
            <div className="text-sm font-semibold">Runtime Configuration</div>
            <p className="text-xs text-muted-foreground">
              Keep this simple: add `config_yml` and optional `prompts_yml`.
              The backend injects model settings from Model Registry. You can
              optionally customize `rails_co`; if left empty, a safe default is
              applied.
            </p>

            <div className="space-y-1.5">
              <Label htmlFor="guardrail-config-yml">config_yml</Label>
              <Textarea
                id="guardrail-config-yml"
                rows={8}
                value={configYml}
                onChange={(event) => setConfigYml(event.target.value)}
                placeholder={getConfigTemplate()}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="guardrail-rails-co">rails_co (Optional)</Label>
              <Textarea
                id="guardrail-rails-co"
                rows={8}
                value={railsCo}
                onChange={(event) => setRailsCo(event.target.value)}
                placeholder='define bot refuse to respond
  ""'
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="guardrail-prompts-yml">prompts_yml</Label>
              <Textarea
                id="guardrail-prompts-yml"
                rows={6}
                value={promptsYml}
                onChange={(event) => setPromptsYml(event.target.value)}
                placeholder={getPromptsTemplate()}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                isSaving ||
                registryModels.length === 0 ||
                isVisibilityInvalid ||
                guardrailNameAvailability.isFetching ||
                guardrailNameAvailability.isNameTaken
              }
            >
              {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isEditMode ? "Save Changes" : "Create Guardrail"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
