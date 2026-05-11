import { ChevronDown, Loader2 } from "lucide-react";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import {
  PREDEFINED_GUARDRAIL_TEMPLATES,
} from "@/constants/predefined-guardrail-templates";

interface EditGuardrailModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  guardrail?: GuardrailInfo | null;
  frameworkId?: "nemo" | "arize";
  readOnly?: boolean;
}

const CATEGORY_OPTIONS = [
  "content-safety",
  "jailbreak",
  "topic-control",
  "pii-masking",
  "fact-checking",
  "sensitive-data-removal",
  "output-filtering",
  "dialog-control",
  "retrieval-validation",
  "execution-validation",
];

const getConfigTemplate = (): string => {
  return `rails:
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
  readOnly = false,
}: EditGuardrailModalProps) {
  const { t } = useTranslation();
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
  const [visibilityScope, setVisibilityScope] = useState<"private" | "department" | "organization">("private");
  const [orgId, setOrgId] = useState("");
  const [deptId, setDeptId] = useState("");
  const [publicDeptIds, setPublicDeptIds] = useState<string[]>([]);
  const [visibilityOptions, setVisibilityOptions] = useState<{
    organizations: { id: string; name: string }[];
    departments: { id: string; name: string; org_id: string }[];
  }>({ organizations: [], departments: [] });
  const canMultiDept = role === "super_admin" || role === "root";
  const departmentsForSelectedOrg = useMemo(
    () =>
      visibilityOptions.departments.filter((d) => !orgId || d.org_id === orgId),
    [visibilityOptions.departments, orgId],
  );
  const selectedDeptLabel = useMemo(() => {
    const selectedIds = canMultiDept ? publicDeptIds : deptId ? [deptId] : [];
    if (selectedIds.length === 0) return t("Select departments");
    const names = departmentsForSelectedOrg
      .filter((dept) => selectedIds.includes(dept.id))
      .map((dept) => dept.name);
    if (names.length === 0) return t("Select departments");
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  }, [canMultiDept, departmentsForSelectedOrg, deptId, publicDeptIds]);
  const handleVisibilityScopeChange = (
    scope: "private" | "department" | "organization",
  ) => {
    setVisibilityScope(scope);
    if (scope !== "department") {
      setPublicDeptIds([]);
      if (scope === "organization") {
        setDeptId("");
      }
    }
    if (scope === "private") {
      setPublicDeptIds([]);
    }
  };

  const [customCategory, setCustomCategory] = useState("");

  // -- Predefined template selection -----------------------------------------
  const [selectedTemplateId, setSelectedTemplateId] = useState("");

  const handleTemplateSelect = (templateId: string) => {
    setSelectedTemplateId(templateId);

    if (!templateId) {
      // Reset to blank defaults when "Custom" is selected
      setName("");
      setDescription("");
      setCategory("");
      setCustomCategory("");
      setConfigYml(getConfigTemplate());
      setPromptsYml(getPromptsTemplate());
      setRailsCo("");
      return;
    }

    const template = PREDEFINED_GUARDRAIL_TEMPLATES.find(
      (t) => t.id === templateId,
    );
    if (!template) return;

    setName(template.name);
    setDescription(template.description);
    setCategory(template.category);
    setConfigYml(template.configYml);
    setPromptsYml(template.promptsYml);
    setRailsCo(template.railsCo);
  };
  // --------------------------------------------------------------------------

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
      setSelectedTemplateId("");

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
      setSelectedTemplateId("");
    }
  }, [guardrail, open, registryModels, defaultModelId]);

  useEffect(() => {
    if (!open) return;
    api.get(`${getURL("GUARDRAILS_CATALOGUE")}/visibility-options`).then((res) => {
      const options = res.data || {
        organizations: [],
        departments: [],
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
      setVisibilityScope(
        guardrail.visibility === "public"
          ? guardrail.public_scope === "organization"
            ? "organization"
            : "department"
          : "private",
      );
      setOrgId(guardrail.org_id || "");
      setDeptId(guardrail.dept_id || "");
      setPublicDeptIds(guardrail.public_dept_ids || []);
    } else {
      setVisibilityScope("private");
      setPublicDeptIds([]);
    }
  }, [guardrail, open]);

  useEffect(() => {
    if (!open || visibilityScope === "private") return;

    if (visibilityScope === "organization") {
      if ((role === "developer" || role === "department_admin") && !orgId && visibilityOptions.organizations.length > 0) {
        setOrgId(visibilityOptions.organizations[0].id);
      }
      return;
    }

    if (!canMultiDept && !deptId && visibilityOptions.departments.length > 0) {
      const firstDept = visibilityOptions.departments[0];
      setDeptId(firstDept.id);
      setOrgId((prev) => prev || firstDept.org_id);
      return;
    }

    if (canMultiDept) {
      const firstDept = departmentsForSelectedOrg[0] || visibilityOptions.departments[0];
      if (!firstDept) return;
      const hasSelectedDept = publicDeptIds.some((id) =>
        departmentsForSelectedOrg.some((dept) => dept.id === id),
      );
      if (!orgId) {
        setOrgId(firstDept.org_id);
      }
      if (publicDeptIds.length === 0 || !hasSelectedDept) {
        setPublicDeptIds([firstDept.id]);
      }
    }
  }, [
    open,
    visibilityScope,
    role,
    orgId,
    deptId,
    publicDeptIds,
    departmentsForSelectedOrg,
    visibilityOptions.organizations,
    visibilityOptions.departments,
  ]);

  const isSaving = createMutation.isPending || updateMutation.isPending;
  const effectiveNameScope = useMemo(() => {
    let effectiveOrgId: string | null = orgId || null;
    let effectiveDeptId: string | null = deptId || null;

    if (visibilityScope !== "private") {
      if (visibilityScope === "organization") {
        effectiveDeptId = null;
      } else if (visibilityScope === "department") {
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
    visibilityScope,
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
    visibilityScope !== "private" &&
    (
      (visibilityScope === "organization" && !orgId) ||
      (visibilityScope === "department" &&
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
        title: t("Name already taken"),
        list: [guardrailNameAvailability.reason || t("Please choose a different name.")],
      });
      return;
    }

    if (!modelRegistryId) {
      setErrorData({
        title: t("Model is required"),
        list: [t("Please select a model from Model Registry.")],
      });
      return;
    }

    if (status === "active" && configYml.trim() === "") {
      setErrorData({
        title: t("config_yml is required"),
        list: [t("Active guardrails require config_yml. prompts_yml is optional.")],
      });
      return;
    }

    let runtimeConfig: GuardrailCreateOrUpdatePayload["runtimeConfig"] = null;
    try {
      runtimeConfig = buildRuntimeConfig();
    } catch (error) {
      setErrorData({ title: t("Invalid runtime config"), list: [String(error)] });
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
      visibility: visibilityScope === "private" ? "private" : "public",
      public_scope: visibilityScope === "private" ? null : visibilityScope,
      public_dept_ids: visibilityScope === "department" ? (canMultiDept ? publicDeptIds : deptId ? [deptId] : []) : [],
    };

    try {
      if (isEditMode && guardrail?.id) {
        await updateMutation.mutateAsync({ id: guardrail.id, payload });
        setSuccessData({ title: t('Guardrail "{{name}}" updated.', { name: payload.name }) });
      } else {
        await createMutation.mutateAsync(payload);
        setSuccessData({ title: t('Guardrail "{{name}}" created.', { name: payload.name }) });
      }
      onOpenChange(false);
    } catch (error) {
      setErrorData({
        title: isEditMode
          ? t("Failed to update guardrail")
          : t("Failed to create guardrail"),
        list: [String(error)],
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {readOnly ? t("View Guardrail (Production - Read Only)") : isEditMode ? t("Edit Guardrail") : t("Add Guardrail")}
          </DialogTitle>
          <DialogDescription>
            {readOnly
              ? t("This is a frozen production copy. Configuration cannot be modified.")
              : t("Configure guardrail metadata and NeMo runtime files. You only need `config_yml` and optional `prompts_yml`. Model details and credentials come from Model Registry.")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Predefined Guardrails dropdown -- only shown when adding */}
          {!isEditMode && !readOnly && (
            <div className="space-y-1.5 rounded-md border border-dashed border-primary/40 bg-primary/5 p-4">
              <Label htmlFor="guardrail-template" className="text-sm font-semibold">
                {t("Predefined Guardrails")}
              </Label>
              <p className="text-xs text-muted-foreground">
                Select a template to auto-populate the configuration, or choose
                &quot;Custom&quot; to start from scratch.
              </p>
              <select
                id="guardrail-template"
                value={selectedTemplateId}
                onChange={(event) => handleTemplateSelect(event.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="">{t("Custom (blank template)")}</option>
                {PREDEFINED_GUARDRAIL_TEMPLATES.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
              {selectedTemplateId && (
                <p className="text-xs text-muted-foreground italic">
                  {PREDEFINED_GUARDRAIL_TEMPLATES.find(
                    (t) => t.id === selectedTemplateId,
                  )?.description}
                </p>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="guardrail-name">{t("Name")} *</Label>
              <Input
                id="guardrail-name"
                required
                readOnly={readOnly}
                disabled={readOnly}
                placeholder={t("NeMo Content Safety")}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              {name.trim().length > 0 &&
                !guardrailNameAvailability.isFetching &&
                guardrailNameAvailability.isNameTaken && (
                  <p className="text-xs font-medium text-red-500">
                    {guardrailNameAvailability.reason ??
                      t("This name is already taken in the selected scope.")}
                  </p>
                )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="guardrail-model">{t("Model Registry Entry")} *</Label>
              <select
                id="guardrail-model"
                required
                value={modelRegistryId}
                onChange={(event) => setModelRegistryId(event.target.value)}
                disabled={readOnly || isModelsLoading || registryModels.length === 0}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                {registryModels.length === 0 ? (
                  <option value="">
                    {isModelsLoading
                      ? t("Loading models...")
                      : t("No models in registry")}
                  </option>
                ) : (
                  <>
                    <option value="" disabled>
                      {t("Select a model")}
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
                  {t("Provider")}:{" "}
                  <span className="font-medium">{selectedModel.provider}</span>{" "}
                  | {t("Model")}:{" "}
                  <span className="font-medium">
                    {selectedModel.model_name}
                  </span>
                </p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="guardrail-description">{t("Description")}</Label>
            <Textarea
              id="guardrail-description"
              rows={2}
              readOnly={readOnly}
              disabled={readOnly}
              placeholder={t("What this guardrail enforces")}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          <div className="rounded-lg border border-border p-4">
            <div className="mb-4">
              <Label className="mb-1.5 block">{t("Tenancy")}</Label>
              <p className="text-xs text-muted-foreground">
                {t("Guardrails use direct tenancy only. No approval flow applies here.")}
              </p>
            </div>

            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label>{t("Visibility Scope")}</Label>
                <select
                  value={visibilityScope}
                  onChange={(event) =>
                    handleVisibilityScopeChange(
                      event.target.value as "private" | "department" | "organization",
                    )
                  }
                  disabled={readOnly}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="private">{t("Private")}</option>
                  <option value="department">{t("Department")}</option>
                  <option value="organization">{t("Organization")}</option>
                </select>
              </div>

              {visibilityScope === "organization" && (
                <div className="space-y-1.5">
                  <Label>{t("Organization")}</Label>
                  <select
                    value={orgId}
                    onChange={(event) => setOrgId(event.target.value)}
                    disabled={readOnly || role === "developer" || role === "department_admin"}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-80"
                  >
                    <option value="">{t("Select organization")}</option>
                    {visibilityOptions.organizations.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {visibilityScope === "department" && (
                <>
                  {canMultiDept && (
                    <div className="space-y-1.5">
                      <Label>{t("Organization")}</Label>
                      <select
                        value={orgId}
                        onChange={(event) => {
                          setOrgId(event.target.value);
                          setPublicDeptIds([]);
                        }}
                        disabled={readOnly}
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      >
                        <option value="">{t("Select organization")}</option>
                        {visibilityOptions.organizations.map((org) => (
                          <option key={org.id} value={org.id}>
                            {org.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <Label>{canMultiDept ? t("Departments") : t("Department")}</Label>
                    {canMultiDept ? (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="outline"
                            disabled={readOnly}
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
                        disabled
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-80"
                      >
                        <option value="">{t("Select department")}</option>
                        {visibilityOptions.departments.map((dept) => (
                          <option key={dept.id} value={dept.id}>
                            {dept.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="space-y-1.5 md:col-span-2">
              <Label htmlFor="guardrail-category">{t("Category")} *</Label>
              <select
                id="guardrail-category"
                required={!customCategory}
                value={CATEGORY_OPTIONS.includes(category) ? category : "__custom__"}
                onChange={(event) => {
                  const val = event.target.value;
                  if (val === "__custom__") {
                    setCustomCategory("");
                    setCategory("");
                  } else {
                    setCustomCategory("");
                    setCategory(val);
                  }
                }}
                disabled={readOnly}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
                <option value="__custom__">{t("Other (custom)")}</option>
              </select>
              {(!CATEGORY_OPTIONS.includes(category) || category === "") && (
                <Input
                  placeholder={t("Enter custom category (e.g. compliance-check)")}
                  required
                  readOnly={readOnly}
                  disabled={readOnly}
                  value={customCategory || (!CATEGORY_OPTIONS.includes(category) ? category : "")}
                  onChange={(event) => {
                    const val = event.target.value;
                    setCustomCategory(val);
                    setCategory(val);
                  }}
                  className="mt-1.5"
                />
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="guardrail-status">{t("Status")} *</Label>
              <select
                id="guardrail-status"
                required
                value={status}
                onChange={(event) =>
                  setStatus(event.target.value as "active" | "inactive")
                }
                disabled={readOnly}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="active">{t("active")}</option>
                <option value="inactive">{t("inactive")}</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-2 text-sm">
            <input
              id="guardrail-custom"
              type="checkbox"
              checked={isCustom}
              onChange={(event) => setIsCustom(event.target.checked)}
              disabled={readOnly}
              className="h-4 w-4 rounded border-input"
            />
            <Label htmlFor="guardrail-custom" className="text-sm">
              {t("Mark as custom guardrail")}
            </Label>
          </div>

          <div className="space-y-3 rounded-md border p-4">
            <div className="text-sm font-semibold">{t("Runtime Configuration")}</div>
            <p className="text-xs text-muted-foreground">
              {t("Keep this simple: add `config_yml` and optional `prompts_yml`. The backend injects model settings from Model Registry. You can optionally customize `rails_co`; if left empty, a safe default is applied.")}
            </p>

            <div className="space-y-1.5">
              <Label htmlFor="guardrail-config-yml">config_yml</Label>
              <Textarea
                id="guardrail-config-yml"
                rows={readOnly ? 12 : 8}
                readOnly={readOnly}
                className={readOnly ? "max-h-[300px] overflow-y-auto font-mono text-xs cursor-default" : ""}
                value={configYml}
                onChange={(event) => setConfigYml(event.target.value)}
                placeholder={getConfigTemplate()}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="guardrail-rails-co">{t("rails_co (Optional)")}</Label>
              <Textarea
                id="guardrail-rails-co"
                rows={readOnly ? 12 : 8}
                readOnly={readOnly}
                className={readOnly ? "max-h-[300px] overflow-y-auto font-mono text-xs cursor-default" : ""}
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
                rows={readOnly ? 12 : 6}
                readOnly={readOnly}
                className={readOnly ? "max-h-[300px] overflow-y-auto font-mono text-xs cursor-default" : ""}
                value={promptsYml}
                onChange={(event) => setPromptsYml(event.target.value)}
                placeholder={getPromptsTemplate()}
              />
            </div>
          </div>

          <DialogFooter>
            {readOnly ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                {t("Close")}
              </Button>
            ) : (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => onOpenChange(false)}
                >
                  {t("Cancel")}
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
                  {isEditMode ? t("Save Changes") : t("Create Guardrail")}
                </Button>
              </>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
