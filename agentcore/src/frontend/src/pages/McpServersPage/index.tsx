import { useContext, useState } from "react";
import {
  Plus,
  Server,
  MoreVertical,
  Edit2,
  Trash2,
  Search,
  XCircle,
  Plug,
  ChevronDown,
  ChevronRight,
  Loader2,
  Wrench,
} from "lucide-react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import Loading from "@/components/ui/loading";
import { Switch } from "@/components/ui/switch";
import { useDeleteMCPServer } from "@/controllers/API/queries/mcp/use-delete-mcp-server";
import { useGetMCPServers } from "@/controllers/API/queries/mcp/use-get-mcp-servers";
import { usePatchMCPServer } from "@/controllers/API/queries/mcp/use-patch-mcp-server";
import { useProbeMCPServer } from "@/controllers/API/queries/mcp/use-probe-mcp-server";
import AddMcpServerModal from "@/modals/mcpServerModal";
import DeleteConfirmationModal from "@/modals/deleteConfirmationModal";
import { AuthContext } from "@/contexts/authContext";
import useAlertStore from "@/stores/alertStore";
import type { McpRegistryType, McpProbeResponse } from "@/types/mcp";

import { useTranslation } from "react-i18next";

export default function MCPServersPage() {
  const { t } = useTranslation();
  const { permissions, userData } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const { data: servers, isLoading } = useGetMCPServers({ active_only: false });
  const deleteMutation = useDeleteMCPServer();
  const patchMutation = usePatchMCPServer();
  const probeMutation = useProbeMCPServer();
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const [searchQuery, setSearchQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [requestOpen, setRequestOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editServer, setEditServer] = useState<McpRegistryType | null>(null);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [serverToDelete, setServerToDelete] = useState<McpRegistryType | null>(null);

  // Probe state
  const [probeResults, setProbeResults] = useState<Record<string, McpProbeResponse>>({});
  const [probingServerId, setProbingServerId] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  // Toggle state (tracks which servers are currently being toggled)
  const [togglingServerId, setTogglingServerId] = useState<string | null>(null);

  const handleEdit = (server: McpRegistryType) => {
    setEditServer(server);
    setEditOpen(true);
  };

  const handleDelete = async (server: McpRegistryType) => {
    try {
      await deleteMutation.mutateAsync({ id: server.id });
      setSuccessData({ title: t("MCP Server \"{{name}}\" deleted.", { name: server.server_name }) });
    } catch (e: any) {
      setErrorData({ title: t("Error deleting server"), list: [e.message] });
    }
  };

  const openDeleteModal = (server: McpRegistryType) => {
    setServerToDelete(server);
    setDeleteModalOpen(true);
  };

  const handleToggleActive = async (server: McpRegistryType) => {
    const newActive = !server.is_active;
    setTogglingServerId(server.id);
    try {
      await patchMutation.mutateAsync({
        id: server.id,
        data: { is_active: newActive },
      });
      setSuccessData({
        title: newActive
          ? t("\"{{name}}\" connected.", { name: server.server_name })
          : t("\"{{name}}\" disconnected.", { name: server.server_name }),
      });
      // Clear probe result when disconnecting
      if (!newActive) {
        setProbeResults((prev) => {
          const next = { ...prev };
          delete next[server.id];
          return next;
        });
        setExpandedRows((prev) => {
          const next = new Set(prev);
          next.delete(server.id);
          return next;
        });
      }
    } catch (e: any) {
      setErrorData({ title: t("Error updating server"), list: [e.message] });
    } finally {
      setTogglingServerId(null);
    }
  };

  const handleProbe = async (server: McpRegistryType) => {
    setProbingServerId(server.id);
    try {
      const result = await probeMutation.mutateAsync({ id: server.id });
      setProbeResults((prev) => ({ ...prev, [server.id]: result }));
      if (result.success) {
        setSuccessData({
          title: t("Connection successful. Found {{count}} tool(s).", {
            count: result.tools_count ?? 0,
          }),
        });
      } else {
        setErrorData({ title: t("Connection failed"), list: [result.message] });
      }
    } catch (e: any) {
      setProbeResults((prev) => ({
        ...prev,
        [server.id]: { success: false, message: e.message },
      }));
      setErrorData({ title: t("Probe failed"), list: [e.message] });
    } finally {
      setProbingServerId(null);
    }
  };

  const toggleRowExpand = (serverId: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(serverId)) {
        next.delete(serverId);
      } else {
        next.add(serverId);
      }
      return next;
    });
  };

  // Filter servers based on search
  const filteredServers = servers?.filter(
    (server) =>
      !searchQuery ||
      server.server_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      server.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const canAddMcp = can("add_new_mcp");
  const canRequestMcp = can("request_new_mcp");
  const currentUserId = userData?.id;

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header - Fixed */}
      <div className="flex flex-shrink-0 items-center justify-between border-b px-8 py-6">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{t("MCP Servers")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Manage MCP Servers for use in your agents")}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Search Bar */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={t("Search servers...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-64 rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>

          {canAddMcp ? (
            <Button
              variant="default"
              onClick={() => setAddOpen(true)}
              data-testid="add-mcp-server-button-page"
            >
              <Plus className="mr-2 h-4 w-4" />
              {t("Add MCP Server")}
            </Button>
          ) : canRequestMcp ? (
            <Button
              variant="default"
              onClick={() => setRequestOpen(true)}
              data-testid="request-mcp-server-button-page"
            >
              <Plus className="mr-2 h-4 w-4" />
              {t("Request MCP Server")}
            </Button>
          ) : null}
        </div>
      </div>

      {/* Table - Scrollable */}
      <div className="flex-1 overflow-auto p-8">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <Loading />
          </div>
        ) : filteredServers && filteredServers.length === 0 ? (
          <div className="flex h-full w-full items-center justify-center">
            <div className="text-center">
              <Server className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <h3 className="mt-4 text-lg font-semibold">{t("No MCP servers found")}</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                {searchQuery
                  ? t("No servers match your search criteria")
                  : t("Get started by adding your first MCP server")}
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="w-full">
                <thead className="bg-muted/50">
                  <tr className="border-b border-border">
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Server Name")}
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Mode")}
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Status")}
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Connection")}
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      {t("Actions")}
                    </th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-border">
                  {filteredServers?.map((server) => (
                    (() => {
                      const isRequester = Boolean(currentUserId && server.requested_by === currentUserId);
                      const isAwaitingApproval = isRequester && server.approval_status === "pending";
                      const controlsDisabled = isAwaitingApproval;
                      const approvalBadge =
                        server.approval_status === "pending"
                          ? { label: t("Awaiting Approval"), cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" }
                          : server.approval_status === "rejected"
                            ? { label: t("Rejected"), cls: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" }
                            : { label: t("Approved"), cls: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" };
                      return (
                    <>
                      <tr key={server.id} className="group hover:bg-muted/50">
                        {/* Server Name */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${server.is_active ? "bg-orange-100 dark:bg-orange-900/30" : "bg-muted"}`}>
                              <ForwardedIconComponent
                                name="Mcp"
                                className={`h-5 w-5 ${server.is_active ? "text-orange-600 dark:text-orange-400" : "text-muted-foreground"}`}
                              />
                            </div>
                            <div className={server.is_active ? "" : "opacity-50"}>
                              <div className="flex items-center gap-2">
                                <div className="font-semibold">{server.server_name}</div>
                                {isRequester && (
                                  <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${approvalBadge.cls}`}>
                                    {approvalBadge.label}
                                  </span>
                                )}
                              </div>
                              {server.description && (
                                <div className="mt-0.5 text-xs text-muted-foreground line-clamp-1">
                                  {server.description}
                                </div>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Mode */}
                        <td className="px-6 py-4">
                          <span className="inline-flex rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium uppercase">
                            {server.mode}
                          </span>
                        </td>

                        {/* Status - Toggle Switch */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={server.is_active}
                              onCheckedChange={() => handleToggleActive(server)}
                              disabled={togglingServerId === server.id || controlsDisabled}
                              className="data-[state=checked]:bg-green-600"
                            />
                            <span className={`text-xs font-medium ${server.is_active ? "text-green-600" : "text-muted-foreground"}`}>
                              {controlsDisabled
                                ? t("Awaiting Approval")
                                : server.is_active
                                  ? t("Connected")
                                  : t("Disconnected")}
                            </span>
                          </div>
                        </td>

                        {/* Connection - Probe */}
                        <td className="px-6 py-4">
                          {controlsDisabled ? (
                            <span className="text-xs text-muted-foreground">
                              {t("Awaiting approval")}
                            </span>
                          ) : !server.is_active ? (
                            <span className="text-xs text-muted-foreground">
                              {t("--")}
                            </span>
                          ) : probingServerId === server.id ? (
                            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              {t("Probing...")}
                            </span>
                          ) : probeResults[server.id] ? (
                            <div className="flex items-center gap-2">
                              {probeResults[server.id].success ? (
                                <span className="inline-flex items-center gap-1 text-xs font-medium text-green-600">
                                  <Plug className="h-3.5 w-3.5" />
                                  {t("OK")}
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 text-xs font-medium text-red-500">
                                  <XCircle className="h-3.5 w-3.5" />
                                  {t("Failed")}
                                </span>
                              )}
                              {probeResults[server.id].success &&
                                probeResults[server.id].tools_count != null && (
                                  <button
                                    onClick={() => toggleRowExpand(server.id)}
                                    className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted"
                                  >
                                    <Wrench className="h-3 w-3" />
                                    {probeResults[server.id].tools_count} {t("tools")}
                                    {expandedRows.has(server.id) ? (
                                      <ChevronDown className="h-3 w-3" />
                                    ) : (
                                      <ChevronRight className="h-3 w-3" />
                                    )}
                                  </button>
                                )}
                            </div>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleProbe(server)}
                              className="h-7 text-xs"
                              disabled={controlsDisabled}
                            >
                              <Plug className="mr-1 h-3.5 w-3.5" />
                              {t("Test Connection")}
                            </Button>
                          )}
                        </td>

                        {/* Actions */}
                        <td className="px-6 py-4">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                className="flex h-8 w-8 items-center justify-center rounded-md opacity-0 transition-colors hover:bg-accent group-hover:opacity-100 disabled:cursor-not-allowed"
                                data-testid={`mcp-server-menu-button-${server.server_name}`}
                                disabled={controlsDisabled}
                              >
                                <MoreVertical className="h-4 w-4 text-foreground" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem
                                onClick={() => handleEdit(server)}
                              >
                                <Edit2 className="mr-2 h-4 w-4" />
                                {t("Edit")}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() => openDeleteModal(server)}
                                className="text-destructive"
                              >
                                <Trash2 className="mr-2 h-4 w-4" />
                                {t("Delete")}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </td>
                      </tr>

                      {/* Expandable tool list */}
                      {expandedRows.has(server.id) &&
                        probeResults[server.id]?.tools &&
                        probeResults[server.id].tools!.length > 0 && (
                          <tr key={`${server.id}-tools`} className="bg-muted/30">
                            <td colSpan={5} className="px-6 py-3">
                              <div className="ml-[52px] space-y-1">
                                <div className="mb-2 text-xs font-medium text-muted-foreground">
                                  {t("Discovered Tools:")}
                                </div>
                                {probeResults[server.id].tools!.map((tool) => (
                                  <div
                                    key={tool.name}
                                    className="flex items-start gap-2 py-1"
                                  >
                                    <Wrench className="mt-0.5 h-3 w-3 flex-shrink-0 text-muted-foreground" />
                                    <div>
                                      <span className="text-sm font-medium">
                                        {tool.name}
                                      </span>
                                      {tool.description && (
                                        <p className="text-xs text-muted-foreground">
                                          {tool.description}
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </td>
                          </tr>
                        )}
                    </>
                      );
                    })()
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-6 text-center text-sm text-muted-foreground">
              {t("Showing {{shown}} of {{total}} servers", {
                shown: filteredServers?.length || 0,
                total: servers?.length || 0,
              })}
            </div>
          </>
        )}
      </div>

      {/* Modals */}
      <AddMcpServerModal open={addOpen} setOpen={setAddOpen} />
      <AddMcpServerModal open={requestOpen} setOpen={setRequestOpen} requestMode />
      {editOpen && editServer && (
        <AddMcpServerModal
          open={editOpen}
          setOpen={setEditOpen}
          initialData={editServer}
        />
      )}
      <DeleteConfirmationModal
        open={deleteModalOpen}
        setOpen={setDeleteModalOpen}
        onConfirm={() => {
          if (serverToDelete) handleDelete(serverToDelete);
          setDeleteModalOpen(false);
          setServerToDelete(null);
        }}
        description={t("MCP Server")}
      />
    </div>
  );
}

