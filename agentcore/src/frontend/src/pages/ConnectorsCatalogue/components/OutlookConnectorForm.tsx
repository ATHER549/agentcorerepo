/**
 * Outlook-specific form fields for the Connector Catalogue modal.
 * Extracted into its own component to minimize merge conflicts
 * with the main ConnectorsCatalogue/index.tsx.
 */

import { Eye, EyeOff, Trash2, Loader2, RefreshCw } from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { api } from "@/controllers/API/api";

interface OutlookFormFields {
  outlook_tenant_id: string;
  outlook_client_id: string;
  outlook_client_secret: string;
}

interface LinkedAccount {
  email: string;
  display_name: string;
  linked_at: string;
}

interface Props {
  form: OutlookFormFields;
  onChange: (field: string, value: string) => void;
  isEditing: boolean;
  connectorId?: string;
}

export default function OutlookConnectorForm({ form, onChange, isEditing, connectorId }: Props) {
  const [showSecret, setShowSecret] = useState(false);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [removingEmail, setRemovingEmail] = useState<string | null>(null);

  const fetchAccounts = useCallback(async () => {
    if (!connectorId) return;
    setLoadingAccounts(true);
    try {
      const res = await api.get(`/api/outlook/${connectorId}/accounts`);
      setAccounts(res.data ?? []);
    } catch {
      setAccounts([]);
    } finally {
      setLoadingAccounts(false);
    }
  }, [connectorId]);

  useEffect(() => {
    if (isEditing && connectorId) {
      fetchAccounts();
    }
  }, [isEditing, connectorId, fetchAccounts]);

  const handleRemoveAccount = async (email: string) => {
    if (!connectorId) return;
    setRemovingEmail(email);
    try {
      await api.delete(`/api/outlook/${connectorId}/accounts/${encodeURIComponent(email)}`);
      setAccounts((prev) => prev.filter((a) => a.email !== email));
    } catch {
      // silently fail — user can retry
    } finally {
      setRemovingEmail(null);
    }
  };

  return (
    <>
      <div>
        <label className="mb-1.5 block text-sm font-medium">Azure Tenant ID</label>
        <input
          value={form.outlook_tenant_id}
          onChange={(e) => onChange("outlook_tenant_id", e.target.value)}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        />
      </div>
      <div>
        <label className="mb-1.5 block text-sm font-medium">Client ID (App Registration)</label>
        <input
          value={form.outlook_client_id}
          onChange={(e) => onChange("outlook_client_id", e.target.value)}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        />
      </div>
      <div>
        <label className="mb-1.5 block text-sm font-medium">
          Client Secret{" "}
          {isEditing && (
            <span className="text-xs text-muted-foreground">(leave blank to keep current)</span>
          )}
        </label>
        <div className="relative">
          <input
            type={showSecret ? "text" : "password"}
            value={form.outlook_client_secret}
            onChange={(e) => onChange("outlook_client_secret", e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 pr-10 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            placeholder={isEditing ? "(unchanged)" : "client-secret"}
          />
          <button
            type="button"
            onClick={() => setShowSecret(!showSecret)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        After saving, use the OAuth flow to link individual mailboxes to this connector.
      </p>

      {isEditing && connectorId && (
        <div className="mt-4 rounded-lg border border-border p-4">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-medium">Linked Mailboxes</h4>
            <button
              type="button"
              onClick={fetchAccounts}
              disabled={loadingAccounts}
              className="text-muted-foreground hover:text-foreground disabled:opacity-50"
              title="Refresh accounts"
            >
              <RefreshCw className={`h-4 w-4 ${loadingAccounts ? "animate-spin" : ""}`} />
            </button>
          </div>

          {loadingAccounts && accounts.length === 0 ? (
            <div className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading accounts...
            </div>
          ) : accounts.length === 0 ? (
            <p className="py-3 text-sm text-muted-foreground">
              No mailboxes linked yet. Use the OAuth flow to link one.
            </p>
          ) : (
            <ul className="space-y-2">
              {accounts.map((acct) => (
                <li
                  key={acct.email}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{acct.email}</p>
                    {acct.display_name && (
                      <p className="truncate text-xs text-muted-foreground">{acct.display_name}</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRemoveAccount(acct.email)}
                    disabled={removingEmail === acct.email}
                    className="ml-2 shrink-0 text-muted-foreground hover:text-destructive disabled:opacity-50"
                    title={`Remove ${acct.email}`}
                  >
                    {removingEmail === acct.email ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
