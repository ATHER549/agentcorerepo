import { DialogClose } from "@radix-ui/react-dialog";
import React, { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import IconComponent from "@/components/common/genericIconComponent";
import { usePostPublishAgent } from "@/controllers/API/queries/agents/use-post-publish-agent";
import BaseModal from "../baseModal";

interface SavedConnection {
  id: string;
  name: string;
  url: string;
  apiKey: string;
  lastUsed: number;
}

const STORAGE_KEY = "agentcore_connections";
const DEFAULT_AGENTCORE_PUBLISH_URL =
  process.env.AGENTCORE_PUBLISH_URL ||
  process.env.BACKEND_URL ||
  `${window.location.protocol}//${window.location.host}`;

// Helper functions for localStorage
const loadConnections = (): SavedConnection[] => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch (error) {
    console.error("Failed to load saved connections:", error);
    return [];
  }
};

const saveConnection = (url: string, apiKey: string, name?: string) => {
  try {
    const connections = loadConnections();
    const id = `${url}-${Date.now()}`;
    const connectionName = name || new URL(url).hostname;

    // Check if connection already exists (by URL)
    const existingIndex = connections.findIndex((c) => c.url === url);

    if (existingIndex >= 0) {
      // Update existing connection
      connections[existingIndex] = {
        ...connections[existingIndex],
        apiKey,
        lastUsed: Date.now(),
      };
    } else {
      // Add new connection
      connections.push({
        id,
        name: connectionName,
        url,
        apiKey,
        lastUsed: Date.now(),
      });
    }

    // Sort by last used (most recent first)
    connections.sort((a, b) => b.lastUsed - a.lastUsed);

    // Keep only the 5 most recent
    const limited = connections.slice(0, 5);

    localStorage.setItem(STORAGE_KEY, JSON.stringify(limited));
  } catch (error) {
    console.error("Failed to save connection:", error);
  }
};

const deleteConnection = (connectionId: string) => {
  try {
    const connections = loadConnections();
    const filtered = connections.filter((c) => c.id !== connectionId);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
  } catch (error) {
    console.error("Failed to delete connection:", error);
  }
};

interface PublishModalProps {
  agentId: string;
  agentName: string;
  open: boolean;
  setOpen: (open: boolean) => void;
  onSuccess?: (response: any) => void;
}

export default function PublishModal({
  agentId,
  agentName,
  open,
  setOpen,
  onSuccess,
}: PublishModalProps) {
  const [agentcoreUrl, setAgentCoreUrl] = useState(DEFAULT_AGENTCORE_PUBLISH_URL);
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState(agentName);
  const [error, setError] = useState<string | null>(null);
  const [savedConnections, setSavedConnections] = useState<SavedConnection[]>([]);
  const [selectedConnection, setSelectedConnection] = useState<string>("new");
  const [showApiKey, setShowApiKey] = useState(false);

  const publishMutation = usePostPublishAgent();

  useEffect(() => {
    if (open) {
      // Load saved connections when modal opens
      const connections = loadConnections();
      setSavedConnections(connections);

      // Auto-select the most recent connection if available
      if (connections.length > 0) {
        const mostRecent = connections[0];
        setSelectedConnection(mostRecent.id);
        setAgentCoreUrl(mostRecent.url);
        setApiKey(mostRecent.apiKey);
      }
    } else {
      // Clear error when modal closes
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    // Update model name when agent name changes
    setModelName(agentName);
  }, [agentName]);

  const handleConnectionChange = (value: string) => {
    setSelectedConnection(value);

    if (value === "new") {
      // Clear fields for new connection
      setAgentCoreUrl(DEFAULT_AGENTCORE_PUBLISH_URL);
      setApiKey("");
    } else {
      // Load selected connection
      const connection = savedConnections.find((c) => c.id === value);
      if (connection) {
        setAgentCoreUrl(connection.url);
        setApiKey(connection.apiKey);
      }
    }
  };

  const handlePublish = () => {
    if (!modelName.trim()) {
      setError("Please enter a model name");
      return;
    }

    if (!apiKey.trim()) {
      setError("Please enter your AgentCore API key");
      return;
    }

    if (!agentcoreUrl.trim()) {
      setError("Please enter your AgentCore URL");
      return;
    }

    publishMutation.mutate(
      {
        agent_id: agentId,
        agentcore_url: agentcoreUrl,
        agentcore_api_key: apiKey,
        model_name: modelName.trim() || undefined,
      },
      {
        onSuccess: (data) => {
          setError(null);
          // Save connection on successful publish
          saveConnection(agentcoreUrl, apiKey);
          onSuccess?.(data);
          setOpen(false);
          // Reset form
          setApiKey("");
        },
        onError: (err: any) => {
          setError(
            err?.response?.data?.detail || "Failed to publish agent. Please try again.",
          );
        },
      }
    );
  };

  return (
    <BaseModal open={open} setOpen={setOpen} size="medium">
      <BaseModal.Header description="Deploy your agent to AgentCore as a selectable model">
        <span className="pr-2">Publish to AgentCore</span>
        <IconComponent
          name="Globe"
          className="h-6 w-6 pl-1 text-foreground"
          aria-hidden="true"
        />
      </BaseModal.Header>

      <BaseModal.Content>
        <div className="flex flex-col gap-4">
          {/* agent info */}
          <div className="rounded-md bg-muted p-3">
            <div className="text-sm font-medium">agent: {agentName}</div>
            <div className="text-xs text-muted-foreground">ID: {agentId}</div>
          </div>

          {/* Saved Connections Selector */}
          {savedConnections.length > 0 && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="connection-select">AgentCore Connection</Label>
              <Select
                value={selectedConnection}
                onValueChange={handleConnectionChange}
                disabled={publishMutation.isPending}
              >
                <SelectTrigger id="connection-select">
                  <SelectValue placeholder="Select a saved connection" />
                </SelectTrigger>
                <SelectContent>
                  {savedConnections.map((conn) => (
                    <SelectItem key={conn.id} value={conn.id}>
                      <div className="flex items-center gap-2">
                        <IconComponent name="Link" className="h-3 w-3" />
                        <span>{conn.name}</span>
                        <span className="text-xs text-muted-foreground">
                          ({new URL(conn.url).hostname})
                        </span>
                      </div>
                    </SelectItem>
                  ))}
                  <SelectItem value="new">
                    <div className="flex items-center gap-2">
                      <IconComponent name="Plus" className="h-3 w-3" />
                      <span>Add New Connection</span>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Select a previously used AgentCore instance or add a new one
              </p>
            </div>
          )}

          {/* Model Name */}
          <div className="flex flex-col gap-2">
            <Label htmlFor="model-name">
              Model Name in AgentCore
              <span className="ml-1 text-destructive">*</span>
            </Label>
            <Input
              id="model-name"
              type="text"
              placeholder="Enter model name"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              disabled={publishMutation.isPending}
            />
            <p className="text-xs text-muted-foreground">
              The name that will appear in AgentCore's model selector
            </p>
          </div>

          {/* AgentCore URL */}
          <div className="flex flex-col gap-2">
            <Label htmlFor="agentcore-url">
              AgentCore URL
              <span className="ml-1 text-destructive">*</span>
            </Label>
            <Input
              id="agentcore-url"
              type="url"
              placeholder={DEFAULT_AGENTCORE_PUBLISH_URL}
              value={agentcoreUrl}
              onChange={(e) => setAgentCoreUrl(e.target.value)}
              disabled={publishMutation.isPending}
            />
            <p className="text-xs text-muted-foreground">
              The base URL of your AgentCore instance
            </p>
          </div>

          {/* API Key */}
          <div className="flex flex-col gap-2">
            <Label htmlFor="api-key">
              AgentCore API Key
              <span className="ml-1 text-destructive">*</span>
            </Label>
            <div className="relative">
              <Input
                id="api-key"
                type={showApiKey ? "text" : "password"}
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={publishMutation.isPending}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                disabled={publishMutation.isPending}
              >
                {showApiKey ? (
                  <Eye className="h-4 w-4" />
                ) : (
                  <EyeOff className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              Get your API key from AgentCore Settings → Account → API Keys
            </p>
          </div>

          {/* Error message */}
          {error && (
            <Alert variant="destructive">
              <IconComponent name="AlertCircle" className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* Success message */}
          {publishMutation.isSuccess && publishMutation.data && (
            <Alert className="border-green-500 bg-green-50 text-green-900 dark:bg-green-950 dark:text-green-100">
              <IconComponent name="CheckCircle2" className="h-4 w-4" />
              <AlertDescription>
                {publishMutation.data.message}
                <br />
                <span className="text-xs">
                  Model ID: {publishMutation.data.model_id}
                </span>
              </AlertDescription>
            </Alert>
          )}
        </div>
      </BaseModal.Content>

      <BaseModal.Footer>
        <DialogClose asChild>
          <Button
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={publishMutation.isPending}
          >
            Cancel
          </Button>
        </DialogClose>
        <Button
          onClick={handlePublish}
          disabled={publishMutation.isPending}
          className="gap-2"
        >
          {publishMutation.isPending ? (
            <>
              <IconComponent name="Loader2" className="h-4 w-4 animate-spin" />
              Publishing...
            </>
          ) : (
            <>
              <IconComponent name="Upload" className="h-4 w-4" />
              Publish agent
            </>
          )}
        </Button>
      </BaseModal.Footer>
    </BaseModal>
  );
}
