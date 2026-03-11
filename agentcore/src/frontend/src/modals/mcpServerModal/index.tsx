import { useContext, useEffect, useMemo, useState } from "react";
import { ForwardedIconComponent } from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import InputListComponent from "@/components/core/parameterRenderComponent/components/inputListComponent";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { MAX_MCP_SERVER_NAME_LENGTH } from "@/constants/constants";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import { useNameAvailability } from "@/controllers/API/queries/common/use-name-availability";
import { useAddMCPServer } from "@/controllers/API/queries/mcp/use-add-mcp-server";
import { usePatchMCPServer } from "@/controllers/API/queries/mcp/use-patch-mcp-server";
import { useRequestMCPServer } from "@/controllers/API/queries/mcp/use-request-mcp-server";
import { useTestMCPConnection } from "@/controllers/API/queries/mcp/use-test-mcp-connection";
import BaseModal from "@/modals/baseModal";
import IOKeyPairInput from "@/modals/IOModal/components/IOFieldView/components/key-pair-input";
import type {
  McpRegistryType,
  McpRegistryCreateRequest,
  McpTestConnectionResponse,
} from "@/types/mcp";
import type { MCPServerType } from "@/types/mcp";
import { extractMcpServersFromJson } from "@/utils/mcpUtils";
import { parseString } from "@/utils/stringManipulation";
import { cn } from "@/utils/utils";

type VisibilityOptions = {
  organizations: { id: string; name: string }[];
  departments: { id: string; name: string; org_id: string }[];
  private_share_users: { id: string; email: string }[];
};

export default function AddMcpServerModal({
  children,
  initialData,
  requestMode = false,
  open: myOpen,
  setOpen: mySetOpen,
  onSuccess,
}: {
  children?: JSX.Element;
  initialData?: McpRegistryType;
  requestMode?: boolean;
  open?: boolean;
  setOpen?: (a: boolean | ((o?: boolean) => boolean)) => void;
  onSuccess?: (server: string) => void;
}): JSX.Element {
  const [open, setOpen] =
    mySetOpen !== undefined && myOpen !== undefined
      ? [myOpen, mySetOpen]
      : useState(false);
  const { role } = useContext(AuthContext);
  const isEditMode = !!initialData;

  const [type, setType] = useState(
    initialData ? (initialData.mode === "stdio" ? "STDIO" : "SSE") : "SSE",
  );
  const [deploymentEnv, setDeploymentEnv] = useState<"dev" | "uat" | "prod">(
    (() => {
      const normalized = String(initialData?.deployment_env || "DEV").toLowerCase();
      if (normalized === "uat" || normalized === "prod" || normalized === "dev") return normalized;
      return "dev";
    })(),
  );
  const [error, setError] = useState<string | null>(null);
  const addMutation = useAddMCPServer();
  const patchMutation = usePatchMCPServer();
  const requestMutation = useRequestMCPServer();
  const testMutation = useTestMCPConnection();

  const isPending =
    addMutation.isPending || patchMutation.isPending || requestMutation.isPending;
  const [testResult, setTestResult] =
    useState<McpTestConnectionResponse | null>(null);

  const [stdioName, setStdioName] = useState(initialData?.server_name || "");
  const [stdioCommand, setStdioCommand] = useState(initialData?.command || "");
  const [stdioArgs, setStdioArgs] = useState<string[]>(initialData?.args || [""]);
  const [stdioEnv, setStdioEnv] = useState<any>([]);
  const [stdioDescription, setStdioDescription] = useState(initialData?.description || "");

  const [sseName, setSseName] = useState(initialData?.server_name || "");
  const [sseUrl, setSseUrl] = useState(initialData?.url || "");
  const [sseEnv, setSseEnv] = useState<any>([]);
  const [sseHeaders, setSseHeaders] = useState<any>([]);
  const [sseDescription, setSseDescription] = useState(initialData?.description || "");
  const activeNameInput = type === "STDIO" ? stdioName : type === "SSE" ? sseName : "";
  const normalizedActiveName = parseString(activeNameInput, ["snake_case", "no_blank", "lowercase"]).slice(0, MAX_MCP_SERVER_NAME_LENGTH);
  const nameAvailability = useNameAvailability({
    entity: "mcp",
    name: normalizedActiveName,
    exclude_id: initialData?.id ?? null,
    enabled: open && type !== "JSON" && activeNameInput.trim().length > 0,
  });
  const isNameTaken = nameAvailability.isNameTaken;

  const [jsonInput, setJsonInput] = useState("");
  const [visibilityScope, setVisibilityScope] = useState<"private" | "department" | "organization">(() => {
    if (initialData?.visibility === "public") {
      return initialData?.public_scope === "organization" ? "organization" : "department";
    }
    return "private";
  });
  const [orgId, setOrgId] = useState(initialData?.org_id || "");
  const [deptId, setDeptId] = useState(initialData?.dept_id || "");
  const [publicDeptIds, setPublicDeptIds] = useState<string[]>(
    initialData?.public_dept_ids || [],
  );
  const [sharedUserEmails, setSharedUserEmails] = useState<string[]>([]);
  const [visibilityOptions, setVisibilityOptions] = useState<VisibilityOptions>({
    organizations: [],
    departments: [],
    private_share_users: [],
  });

  const departmentsForSelectedOrg = useMemo(
    () =>
      visibilityOptions.departments.filter((d) => !orgId || d.org_id === orgId),
    [visibilityOptions.departments, orgId],
  );

  function parseEnvList(envList: any): Record<string, string> {
    const env: Record<string, string> = {};
    if (Array.isArray(envList)) {
      envList.forEach((obj) => {
        const key = Object.keys(obj)[0];
        if (key && key.trim() !== "") env[key] = obj[key];
      });
    }
    return env;
  }

  function buildTenancyPayload() {
    const isPublic = visibilityScope !== "private";
    return {
      visibility: isPublic ? "public" : "private",
      public_scope: isPublic ? visibilityScope : null,
      org_id: orgId || undefined,
      dept_id: deptId || undefined,
      public_dept_ids:
        visibilityScope === "department"
          ? publicDeptIds
          : [],
      shared_user_emails:
        role === "department_admin" && visibilityScope === "private"
          ? sharedUserEmails
          : [],
    };
  }

  async function testConnection() {
    setTestResult(null);
    setError(null);
    try {
      if (type === "STDIO") {
        if (!stdioCommand.trim()) return setError("Command is required to test connection.");
        const result = await testMutation.mutateAsync({
          mode: "stdio",
          command: stdioCommand,
          args: stdioArgs.filter((a) => a.trim() !== ""),
          env_vars: parseEnvList(stdioEnv),
        });
        setTestResult(result);
      } else if (type === "SSE") {
        if (!sseUrl.trim()) return setError("URL is required to test connection.");
        const result = await testMutation.mutateAsync({
          mode: "sse",
          url: sseUrl,
          env_vars: parseEnvList(sseEnv),
          headers: parseEnvList(sseHeaders),
        });
        setTestResult(result);
      }
    } catch (err: any) {
      setTestResult({ success: false, message: err?.message || "Connection failed." });
    }
  }

  async function submitForm() {
    setError(null);
    if (type !== "JSON" && isNameTaken) {
      setError(nameAvailability.reason || "Name is already taken.");
      return;
    }
    const tenancyPayload = buildTenancyPayload();

    if (type === "STDIO") {
      if (!stdioName.trim() || !stdioCommand.trim()) return setError("Name and command are required.");
      const serverName = parseString(stdioName, ["snake_case", "no_blank", "lowercase"]).slice(0, MAX_MCP_SERVER_NAME_LENGTH);
      try {
        const payload: McpRegistryCreateRequest = {
          server_name: serverName,
          description: stdioDescription || null,
          mode: "stdio",
          deployment_env: deploymentEnv,
          command: stdioCommand,
          args: stdioArgs.filter((a) => a.trim() !== ""),
          env_vars: parseEnvList(stdioEnv),
          ...tenancyPayload,
        };
        if (isEditMode && initialData) {
          await patchMutation.mutateAsync({ id: initialData.id, data: payload });
        } else if (requestMode) {
          await requestMutation.mutateAsync(payload);
        } else {
          await addMutation.mutateAsync(payload);
        }
        onSuccess?.(serverName);
        setOpen(false);
        resetForm();
      } catch (err: any) {
        setError(err?.message || "Failed to save MCP server.");
      }
      return;
    }

    if (type === "SSE") {
      if (!sseName.trim() || !sseUrl.trim()) return setError("Name and URL are required.");
      const serverName = parseString(sseName, ["snake_case", "no_blank", "lowercase"]).slice(0, MAX_MCP_SERVER_NAME_LENGTH);
      try {
        const payload: McpRegistryCreateRequest = {
          server_name: serverName,
          description: sseDescription || null,
          mode: "sse",
          deployment_env: deploymentEnv,
          url: sseUrl,
          env_vars: parseEnvList(sseEnv),
          headers: parseEnvList(sseHeaders),
          ...tenancyPayload,
        };
        if (isEditMode && initialData) {
          await patchMutation.mutateAsync({ id: initialData.id, data: payload });
        } else if (requestMode) {
          await requestMutation.mutateAsync(payload);
        } else {
          await addMutation.mutateAsync(payload);
        }
        onSuccess?.(serverName);
        setOpen(false);
        resetForm();
      } catch (err: any) {
        setError(err?.message || "Failed to save MCP server.");
      }
      return;
    }

    if (type === "JSON") {
      if (!jsonInput.trim()) return setError("JSON configuration is required.");
      let servers: MCPServerType[];
      try {
        servers = extractMcpServersFromJson(jsonInput);
      } catch (err: any) {
        return setError(err?.message || "Invalid JSON format.");
      }
      try {
        for (const srv of servers) {
          const serverName = parseString(srv.name, ["snake_case", "no_blank", "lowercase"]).slice(0, MAX_MCP_SERVER_NAME_LENGTH);
          const mode: "sse" | "stdio" = srv.command ? "stdio" : "sse";
          const createReq: McpRegistryCreateRequest = {
            server_name: serverName,
            mode,
            deployment_env: deploymentEnv,
            ...(mode === "stdio" && {
              command: srv.command,
              args: srv.args?.filter((a) => a.trim() !== ""),
            }),
            ...(mode === "sse" && {
              url: srv.url,
              headers: srv.headers && Object.keys(srv.headers).length > 0 ? srv.headers : undefined,
            }),
            env_vars: srv.env && Object.keys(srv.env).length > 0 ? srv.env : undefined,
            ...tenancyPayload,
          };
          if (requestMode) {
            await requestMutation.mutateAsync(createReq);
          } else {
            await addMutation.mutateAsync(createReq);
          }
        }
        onSuccess?.(servers[0]?.name || "");
        setOpen(false);
        resetForm();
      } catch (err: any) {
        setError(err?.message || "Failed to import MCP server(s).");
      }
    }
  }

  function resetForm() {
    setStdioName("");
    setStdioCommand("");
    setStdioArgs([""]);
    setStdioEnv([]);
    setStdioDescription("");
    setSseName("");
    setSseUrl("");
    setSseEnv([]);
    setSseHeaders([]);
    setSseDescription("");
    setJsonInput("");
    setDeploymentEnv("dev");
    setVisibilityScope("private");
    setOrgId("");
    setDeptId("");
    setPublicDeptIds([]);
    setSharedUserEmails([]);
    setError(null);
    setTestResult(null);
  }

  useEffect(() => {
    if (!open) return;
    setType(initialData ? (initialData.mode === "stdio" ? "STDIO" : "SSE") : "SSE");
    setError(null);
    setStdioName(initialData?.server_name || "");
    setStdioCommand(initialData?.command || "");
    setStdioArgs(initialData?.args || [""]);
    setStdioEnv([]);
    setStdioDescription(initialData?.description || "");
    setSseName(initialData?.server_name || "");
    setSseUrl(initialData?.url || "");
    setSseEnv([]);
    setSseHeaders([]);
    setSseDescription(initialData?.description || "");
    {
      const normalized = String(initialData?.deployment_env || "DEV").toLowerCase();
      setDeploymentEnv(normalized === "uat" || normalized === "prod" || normalized === "dev" ? (normalized as "dev" | "uat" | "prod") : "dev");
    }
    setVisibilityScope(
      initialData?.visibility === "public"
        ? (initialData?.public_scope === "organization" ? "organization" : "department")
        : "private",
    );
    setOrgId(initialData?.org_id || "");
    setDeptId(initialData?.dept_id || "");
    setPublicDeptIds(initialData?.public_dept_ids || []);
    setSharedUserEmails([]);
  }, [open, initialData]);

  useEffect(() => {
    if (!open) return;
    api.get("api/mcp/registry/visibility-options").then((res) => {
      const options: VisibilityOptions = res.data || {
        organizations: [],
        departments: [],
        private_share_users: [],
      };
      setVisibilityOptions(options);
      if (!orgId) setOrgId(options.organizations?.[0]?.id || "");
      if (!deptId) setDeptId(options.departments?.[0]?.id || "");
    });
  }, [open]);

  useEffect(() => {
    if (!open || visibilityScope === "private") return;
    const canMultiDept = role === "super_admin" || role === "root";
    if (visibilityScope === "organization") {
      if ((role === "developer" || role === "department_admin") && !orgId && visibilityOptions.organizations.length > 0) {
        setOrgId(visibilityOptions.organizations[0].id);
      }
      return;
    }
    if (!canMultiDept && !deptId && visibilityOptions.departments.length > 0) {
      const firstDept = visibilityOptions.departments[0];
      setDeptId(firstDept.id);
      if (!orgId) setOrgId(firstDept.org_id);
    }
  }, [open, visibilityScope, role, orgId, deptId, visibilityOptions]);

  const handleTypeChange = (val: string) => {
    setType(val);
    setError(null);
    setTestResult(null);
  };

  return (
    <BaseModal open={open} setOpen={setOpen} size="small-update" onSubmit={submitForm} className="!p-0">
      <BaseModal.Trigger>{children}</BaseModal.Trigger>
      <BaseModal.Content className="flex flex-col justify-between overflow-hidden">
        <div className="flex h-full w-full flex-col overflow-hidden">
          <div className="flex flex-col gap-3 p-4 tracking-normal">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ForwardedIconComponent name="Server" className="h-4 w-4 text-primary" aria-hidden="true" />
              {isEditMode ? "Edit MCP Server" : requestMode ? "Request MCP Server" : "Register MCP Server"}
            </div>
          </div>
          <div className="flex h-full w-full flex-col overflow-hidden">
            <div className="flex flex-col gap-4 border-y p-4">
              <div className="flex flex-col gap-2">
                <Label className="!text-mmd">Transport</Label>
                <Select value={type} onValueChange={handleTypeChange} disabled={isEditMode}>
                  <SelectTrigger data-testid="connection-type-select" className="w-full">
                    <SelectValue placeholder="Select transport..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="SSE">SSE</SelectItem>
                    <SelectItem value="STDIO">STDIO</SelectItem>
                    {!isEditMode && <SelectItem value="JSON">JSON</SelectItem>}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-2">
                <Label className="!text-mmd">Environment</Label>
                <Select value={deploymentEnv} onValueChange={(value) => setDeploymentEnv(value as "dev" | "uat" | "prod")} disabled={isPending}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select environment..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="dev">DEV</SelectItem>
                    <SelectItem value="uat">UAT</SelectItem>
                    <SelectItem value="prod">PROD</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {error && (
                <ShadTooltip content={error}>
                  <div className={cn("truncate text-xs font-medium text-red-500")}>{error}</div>
                </ShadTooltip>
              )}
              {type !== "JSON" && activeNameInput.trim().length > 0 && !nameAvailability.isFetching && isNameTaken && (
                <div className="text-xs font-medium text-red-500">
                  {nameAvailability.reason ?? "Name is already taken."}
                </div>
              )}
              <div className="flex max-h-[380px] flex-col gap-4 overflow-y-auto" id="global-variable-modal-inputs">
                {type === "STDIO" && (
                  <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-2">
                      <Label className="flex items-start gap-1 !text-mmd">Name <span className="text-red-500">*</span></Label>
                      <Input value={stdioName} onChange={(e) => setStdioName(e.target.value)} placeholder="Server name" data-testid="stdio-name-input" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Description</Label>
                      <Input value={stdioDescription} onChange={(e) => setStdioDescription(e.target.value)} placeholder="Brief description" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="flex items-start gap-1 !text-mmd">Command<span className="text-red-500">*</span></Label>
                      <Input value={stdioCommand} onChange={(e) => setStdioCommand(e.target.value)} placeholder="Command to run" data-testid="stdio-command-input" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Arguments</Label>
                      <InputListComponent value={stdioArgs} handleOnNewValue={({ value }) => setStdioArgs(value)} disabled={isPending} placeholder="Add argument" listAddLabel="Add Argument" editNode={false} id="stdio-args" data-testid="stdio-args-input" />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Environment Variables</Label>
                      <IOKeyPairInput value={stdioEnv} onChange={setStdioEnv} duplicateKey={false} isList={true} isInputField={true} testId="stdio-env" />
                    </div>
                  </div>
                )}
                {type === "SSE" && (
                  <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-2">
                      <Label className="flex items-start gap-1 !text-mmd">Name<span className="text-red-500">*</span></Label>
                      <Input value={sseName} onChange={(e) => setSseName(e.target.value)} placeholder="Server name" data-testid="sse-name-input" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Description</Label>
                      <Input value={sseDescription} onChange={(e) => setSseDescription(e.target.value)} placeholder="Brief description" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="flex items-start gap-1 !text-mmd">Endpoint URL<span className="text-red-500">*</span></Label>
                      <Input value={sseUrl} onChange={(e) => setSseUrl(e.target.value)} placeholder="Server URL" data-testid="sse-url-input" disabled={isPending} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Headers</Label>
                      <IOKeyPairInput value={sseHeaders} onChange={setSseHeaders} duplicateKey={false} isList={true} isInputField={true} testId="sse-headers" />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Environment Variables</Label>
                      <IOKeyPairInput value={sseEnv} onChange={setSseEnv} duplicateKey={false} isList={true} isInputField={true} testId="sse-env" />
                    </div>
                  </div>
                )}
                <div className="flex flex-col gap-4 rounded-md border p-3">
                  <Label className="!text-mmd">Tenancy</Label>
                  <div className="flex flex-col gap-2">
                    <Label className="!text-mmd">Visibility Scope</Label>
                    <select
                      value={visibilityScope}
                      onChange={(e) => setVisibilityScope(e.target.value as "private" | "department" | "organization")}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      disabled={isPending}
                    >
                      <option value="private">private</option>
                      <option value="department">department</option>
                      <option value="organization">organization</option>
                    </select>
                  </div>
                  {visibilityScope === "organization" && (
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Organization</Label>
                      <select value={orgId} onChange={(event) => setOrgId(event.target.value)} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" disabled={isPending || role === "developer" || role === "department_admin"}>
                        <option value="">Select organization</option>
                        {visibilityOptions.organizations.map((org) => (
                          <option key={org.id} value={org.id}>{org.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  {visibilityScope === "department" && (
                    <>
                      {(role === "super_admin" || role === "root") && (
                        <div className="flex flex-col gap-2">
                          <Label className="!text-mmd">Organization</Label>
                          <select value={orgId} onChange={(event) => { setOrgId(event.target.value); setPublicDeptIds([]); }} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" disabled={isPending}>
                            <option value="">Select organization</option>
                            {visibilityOptions.organizations.map((org) => (
                              <option key={org.id} value={org.id}>{org.name}</option>
                            ))}
                          </select>
                        </div>
                      )}
                      <div className="flex flex-col gap-2">
                        <Label className="!text-mmd">Department{role === "super_admin" || role === "root" ? "s" : ""}</Label>
                        {role === "super_admin" || role === "root" ? (
                          <select multiple value={publicDeptIds} onChange={(event) => setPublicDeptIds(Array.from(event.target.selectedOptions).map((o) => o.value))} className="min-h-[88px] rounded-md border border-input bg-background px-3 py-2 text-sm" disabled={isPending}>
                            {departmentsForSelectedOrg.map((dept) => (
                              <option key={dept.id} value={dept.id}>{dept.name}</option>
                            ))}
                          </select>
                        ) : (
                          <select value={deptId} onChange={(event) => setDeptId(event.target.value)} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" disabled={isPending || role === "developer" || role === "department_admin"}>
                            <option value="">Select department</option>
                            {visibilityOptions.departments.map((dept) => (
                              <option key={dept.id} value={dept.id}>{dept.name}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    </>
                  )}
                  {visibilityScope === "private" && role === "department_admin" && (
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">Additional Users (optional)</Label>
                      <select multiple value={sharedUserEmails} onChange={(event) => setSharedUserEmails(Array.from(event.target.selectedOptions).map((o) => o.value))} className="min-h-[88px] rounded-md border border-input bg-background px-3 py-2 text-sm" disabled={isPending}>
                        {visibilityOptions.private_share_users.map((u) => (
                          <option key={u.id} value={u.email}>{u.email}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
                {type === "JSON" && (
                  <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-2">
                      <Label className="!text-mmd">MCP JSON Configuration</Label>
                      <p className="text-xs text-muted-foreground">
                        Paste a standard MCP JSON config. Supports <code className="text-xs">{`{ "mcpServers": { ... } }`}</code>, multiple server objects, or a single server object.
                      </p>
                      <Textarea value={jsonInput} onChange={(e) => setJsonInput(e.target.value)} placeholder={'{\n  "mcpServers": {\n    "server-name": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-everything"]\n    }\n  }\n}'} rows={10} className="font-mono text-xs" data-testid="json-config-input" disabled={isPending} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-2 p-4">
          {testResult && (
            <div className={cn("flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium", testResult.success ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400" : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400")}>
              <ForwardedIconComponent name={testResult.success ? "CheckCircle2" : "XCircle"} className="h-4 w-4 flex-shrink-0" />
              <span className="truncate">{testResult.success ? `Connected - ${testResult.tools_count ?? 0} tool(s) found` : testResult.message}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <div>
              {type !== "JSON" && (
                <Button variant="outline" size="sm" onClick={testConnection} disabled={isPending || testMutation.isPending} loading={testMutation.isPending} data-testid="test-mcp-connection-button">
                  <ForwardedIconComponent name="Plug" className="mr-1.5 h-3.5 w-3.5" />
                  <span className="text-mmd font-normal">Test Connection</span>
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
                <span className="text-mmd font-normal">Cancel</span>
              </Button>
              <Button
                size="sm"
                onClick={submitForm}
                data-testid="add-mcp-server-button"
                loading={isPending}
                disabled={isNameTaken || nameAvailability.isFetching}
              >
                <span className="text-mmd">{isEditMode ? "Save" : requestMode ? "Submit Request" : type === "JSON" ? "Import" : "Register"}</span>
              </Button>
            </div>
          </div>
        </div>
      </BaseModal.Content>
    </BaseModal>
  );
}
