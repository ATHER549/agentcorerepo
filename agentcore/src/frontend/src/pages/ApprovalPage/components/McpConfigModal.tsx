import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useGetMcpApprovalConfig, useUpdateMcpApprovalConfig } from "@/controllers/API/queries/approvals";
import useAlertStore from "@/stores/alertStore";

interface McpConfigModalProps {
  open: boolean;
  approvalId: string | null;
  setOpen: (open: boolean) => void;
  onSaved?: () => void;
}

export default function McpConfigModal({
  open,
  approvalId,
  setOpen,
  onSaved,
}: McpConfigModalProps) {
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const { data, isLoading } = useGetMcpApprovalConfig(
    { approval_id: approvalId || "" },
    { enabled: open && !!approvalId },
  );
  const updateMutation = useUpdateMcpApprovalConfig();

  const [serverName, setServerName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<"sse" | "stdio">("sse");
  const [url, setUrl] = useState("");
  const [command, setCommand] = useState("");
  const [argsText, setArgsText] = useState("");

  useEffect(() => {
    if (!data) return;
    setServerName(data.server_name || "");
    setDescription(data.description || "");
    setMode((data.mode || "sse") as "sse" | "stdio");
    setUrl(data.url || "");
    setCommand(data.command || "");
    setArgsText((data.args || []).join(", "));
  }, [data]);

  const args = useMemo(
    () =>
      argsText
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    [argsText],
  );

  const handleSave = async () => {
    if (!approvalId) return;
    try {
      await updateMutation.mutateAsync({
        approvalId,
        data: {
          server_name: serverName.trim(),
          description: description || null,
          mode,
          ...(mode === "sse"
            ? { url: url.trim() || null }
            : { command: command.trim() || null, args }),
        },
      });
      setSuccessData({ title: `MCP config for "${serverName}" updated.` });
      onSaved?.();
      setOpen(false);
    } catch (e: any) {
      setErrorData({
        title: "Failed to update MCP config",
        list: [e?.message || "Unknown error"],
      });
    }
  };

  if (!open) return null;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-card shadow-lg">
        <div className="flex items-start justify-between border-b p-5">
          <div>
            <h2 className="text-lg font-semibold">MCP Config</h2>
            <p className="text-sm text-muted-foreground">Review and edit MCP server config before approval</p>
          </div>
          <button onClick={() => setOpen(false)} className="rounded-sm opacity-70 hover:opacity-100">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="max-h-[65vh] space-y-4 overflow-y-auto p-5">
          {isLoading ? (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading config...
            </div>
          ) : !data ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              Unable to load MCP config for this approval.
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label>Server Name</Label>
                <Input value={serverName} onChange={(e) => setServerName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <Input value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>Transport</Label>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value as "sse" | "stdio")}
                  className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                >
                  <option value="sse">SSE</option>
                  <option value="stdio">STDIO</option>
                </select>
              </div>
              {mode === "sse" ? (
                <div className="space-y-2">
                  <Label>Endpoint URL</Label>
                  <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
                </div>
              ) : (
                <>
                  <div className="space-y-2">
                    <Label>Command</Label>
                    <Input value={command} onChange={(e) => setCommand(e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label>Args (comma separated)</Label>
                    <Textarea rows={3} value={argsText} onChange={(e) => setArgsText(e.target.value)} />
                  </div>
                </>
              )}
            </>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t p-5">
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={!data || updateMutation.isPending}
          >
            {updateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Save Config
          </Button>
        </div>
      </div>
    </>
  );
}
