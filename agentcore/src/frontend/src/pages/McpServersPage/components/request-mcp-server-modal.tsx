import { useState } from "react";
import { Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import useAlertStore from "@/stores/alertStore";

interface RequestMcpServerModalProps {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export default function RequestMcpServerModal({
  open,
  setOpen,
}: RequestMcpServerModalProps) {
  const [serverName, setServerName] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [justification, setJustification] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);

  const resetForm = () => {
    setServerName("");
    setServerUrl("");
    setJustification("");
  };

  const handleClose = () => {
    setOpen(false);
    resetForm();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    await new Promise((resolve) => setTimeout(resolve, 500));
    setSuccessData({ title: "MCP server request submitted (dummy)" });
    setIsSubmitting(false);
    handleClose();
  };

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm"
        onClick={handleClose}
      />
      <div
        className="fixed left-1/2 top-1/2 z-50 w-full max-w-xl max-h-[90vh] -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-card shadow-lg flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex-shrink-0 border-b p-6">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-semibold">Request MCP Server</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Submit MCP server details for admin review
              </p>
            </div>
            <button
              onClick={handleClose}
              className="rounded-sm opacity-70 transition-opacity hover:opacity-100"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-4">
          <div>
            <Label>Server Name *</Label>
            <Input
              required
              placeholder="e.g., github-tools"
              value={serverName}
              onChange={(e) => setServerName(e.target.value)}
            />
          </div>

          <div>
            <Label>Server URL *</Label>
            <Input
              required
              placeholder="https://example.com/mcp"
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
            />
          </div>

          <div>
            <Label>Business Justification *</Label>
            <Textarea
              required
              rows={4}
              placeholder="Why do you need this MCP server?"
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
            />
          </div>
        </form>

        <div className="flex-shrink-0 border-t p-6">
          <div className="flex items-center gap-3">
            <div className="flex-1" />
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" onClick={handleSubmit} disabled={isSubmitting}>
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Submit Request
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
