import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ForwardedIconComponent } from "@/components/common/genericIconComponent";
import {
  useGetManagedPackages,
  type ManagedPackage,
} from "@/controllers/API/queries/packages/use-get-managed-packages";
import {
  useGetTransitivePackages,
  type TransitivePackage,
} from "@/controllers/API/queries/packages/use-get-transitive-packages";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

type TabKey = "managed" | "transitive";

function InfoTooltip({ text }: { text: string }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="ml-1 inline-flex cursor-help">
            <ForwardedIconComponent
              name="Info"
              className="h-3.5 w-3.5 text-muted-foreground"
            />
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          <p>{text}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <ForwardedIconComponent name="PackageSearch" className="mb-3 h-10 w-10 opacity-40" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Managed table
// ---------------------------------------------------------------------------

function ManagedTable({
  packages,
  search,
}: {
  packages: ManagedPackage[];
  search: string;
}) {
  const { t } = useTranslation();

  const filtered = useMemo(() => {
    if (!search) return packages;
    const q = search.toLowerCase();
    return packages.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.version_spec.toLowerCase().includes(q) ||
        p.resolved_version.toLowerCase().includes(q),
    );
  }, [packages, search]);

  if (filtered.length === 0) {
    return <EmptyState message={search ? t("No packages match your search.") : t("No managed dependencies found.")} />;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full">
        <thead>
          <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
            <th className="px-4 py-3 text-left font-medium">{t("Package")}</th>
            <th className="px-4 py-3 text-left font-medium">{t("Declared")}</th>
            <th className="px-4 py-3 text-left font-medium">{t("Resolved")}</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((pkg) => (
            <tr
              key={pkg.name}
              className="border-b last:border-0 transition-colors hover:bg-muted/30"
            >
              <td className="px-4 py-3 font-mono text-sm">{pkg.name}</td>
              <td className="px-4 py-3 text-sm text-muted-foreground">
                {pkg.version_spec || "*"}
              </td>
              <td className="px-4 py-3 text-sm">
                <Badge variant="outline" size="sm">
                  {pkg.resolved_version}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t px-4 py-2 text-xs text-muted-foreground">
        {t("Showing {{count}} of {{total}} packages", {
          count: filtered.length,
          total: packages.length,
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Transitive table
// ---------------------------------------------------------------------------

function TransitiveTable({
  packages,
  search,
}: {
  packages: TransitivePackage[];
  search: string;
}) {
  const { t } = useTranslation();

  const filtered = useMemo(() => {
    if (!search) return packages;
    const q = search.toLowerCase();
    return packages.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.resolved_version.toLowerCase().includes(q) ||
        p.required_by.some((r) => r.toLowerCase().includes(q)) ||
        p.required_by_details.some(
          (r) => r.name.toLowerCase().includes(q) || r.version.toLowerCase().includes(q),
        ) ||
        p.start_date.toLowerCase().includes(q) ||
        p.end_date.toLowerCase().includes(q),
    );
  }, [packages, search]);

  if (filtered.length === 0) {
    return <EmptyState message={search ? t("No packages match your search.") : t("No transitive dependencies found.")} />;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full">
        <thead>
          <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
            <th className="px-4 py-3 text-left font-medium">{t("Package")}</th>
            <th className="px-4 py-3 text-left font-medium">{t("Version")}</th>
            <th className="px-4 py-3 text-left font-medium">{t("Required By")}</th>
            <th className="px-4 py-3 text-left font-medium">{t("Required By Version")}</th>
            <th className="px-4 py-3 text-left font-medium">{t("Start Date")}</th>
            <th className="px-4 py-3 text-left font-medium">{t("End Date")}</th>
            <th className="px-4 py-3 text-left font-medium">{t("Status")}</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((pkg) => (
            <tr
              key={pkg.id}
              className="border-b last:border-0 transition-colors hover:bg-muted/30"
            >
              <td className="px-4 py-3 font-mono text-sm">{pkg.name}</td>
              <td className="px-4 py-3 text-sm">
                <Badge variant="outline" size="sm">
                  {pkg.resolved_version}
                </Badge>
              </td>
              <td className="px-4 py-3 text-sm text-muted-foreground">
                {pkg.required_by.length > 0 ? (
                  <span>
                    {pkg.required_by.slice(0, 3).join(", ")}
                    {pkg.required_by.length > 3 &&
                      ` +${pkg.required_by.length - 3} more`}
                  </span>
                ) : (
                  "-"
                )}
              </td>
              <td className="px-4 py-3 text-sm text-muted-foreground">
                {pkg.required_by_details.length > 0 ? (
                  <span>
                    {pkg.required_by_details
                      .slice(0, 3)
                      .map((d) => `${d.name}: ${d.version}`)
                      .join(", ")}
                    {pkg.required_by_details.length > 3 &&
                      ` +${pkg.required_by_details.length - 3} more`}
                  </span>
                ) : (
                  "-"
                )}
              </td>
              <td className="px-4 py-3 text-sm text-muted-foreground">{pkg.start_date}</td>
              <td className="px-4 py-3 text-sm text-muted-foreground">{pkg.end_date}</td>
              <td className="px-4 py-3 text-sm">
                <Badge
                  variant="outline"
                  size="sm"
                  className={pkg.is_current ? "border-green-500/50 text-green-600" : ""}
                >
                  {pkg.is_current ? t("Current") : t("Historical")}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t px-4 py-2 text-xs text-muted-foreground">
        {t("Showing {{count}} of {{total}} packages", {
          count: filtered.length,
          total: packages.length,
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const TABS: { key: TabKey; label: string; tooltip: string }[] = [
  {
    key: "managed",
    label: "Managed",
    tooltip:
      "Direct dependencies declared in pyproject.toml and resolved via uv.lock.",
  },
  {
    key: "transitive",
    label: "Transitive",
    tooltip:
      "Indirect dependencies pulled in automatically by your managed packages. Read-only.",
  },
];

export default function PackagesPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<TabKey>("managed");
  const [searchQuery, setSearchQuery] = useState("");

  const { data: managedPackages, isLoading: loadingManaged } =
    useGetManagedPackages();
  const { data: transitivePackages, isLoading: loadingTransitive } =
    useGetTransitivePackages();

  const isLoading =
    (activeTab === "managed" && loadingManaged) ||
    (activeTab === "transitive" && loadingTransitive);

  const counts: Record<TabKey, number> = {
    managed: (managedPackages ?? []).length,
    transitive: (transitivePackages ?? []).length,
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* ── Fixed Header ─────────────────────────────────────────── */}
      <div className="flex flex-shrink-0 items-center justify-between border-b px-8 py-6">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h1 className="text-2xl font-semibold">
              {t("Dependency Governance")}
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t(
              "View and manage project packages. Dependencies are read from pyproject.toml and resolved via uv.lock.",
            )}
          </p>
        </div>

        {/* Search */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={t("Search packages...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-64 rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>
      </div>

      {/* ── Tabs ─────────────────────────────────────────────────── */}
      <div className="flex flex-shrink-0 gap-1 border-b px-8 pt-2">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key);
                setSearchQuery("");
              }}
              className={`relative flex items-center gap-2 rounded-t-md px-4 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-background text-foreground after:absolute after:bottom-[-1px] after:left-0 after:h-[2px] after:w-full after:bg-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t(tab.label)}
              {counts[tab.key] > 0 && (
                <Badge
                  variant={isActive ? "secondaryStatic" : "gray"}
                  size="sm"
                >
                  {counts[tab.key]}
                </Badge>
              )}
              <InfoTooltip text={t(tab.tooltip)} />
            </button>
          );
        })}
      </div>

      {/* ── Scrollable Content ───────────────────────────────────── */}
      <div className="flex-1 overflow-auto p-8">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <ForwardedIconComponent
              name="Loader2"
              className="h-8 w-8 animate-spin text-muted-foreground"
            />
          </div>
        ) : (
          <>
            {activeTab === "managed" && (
              <ManagedTable
                packages={managedPackages ?? []}
                search={searchQuery}
              />
            )}
            {activeTab === "transitive" && (
              <TransitiveTable
                packages={transitivePackages ?? []}
                search={searchQuery}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
