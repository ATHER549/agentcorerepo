import {
  Search,
  Activity,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Loading from "@/components/ui/loading";
import { useGetVectorDBCatalogue } from "@/controllers/API/queries/vector-db/use-get-vector-db-catalogue";
import { getProviderIcon } from "@/utils/logo_provider";

interface VectorDBType {
  id: string;
  name: string;
  description: string;
  provider: string;
  deployment: "SaaS" | "Self-hosted" | "Hybrid";
  dimensions: string;
  indexType: string;
  status: "connected" | "disconnected" | "configuring";
  vectorCount: string;
  isCustom: boolean;
}

interface VectorDBViewProps {
  vectorDBs?: VectorDBType[];
  setSearch?: (search: string) => void;
  onEditVectorDB?: (vectorDB: VectorDBType) => void;
  onDeleteVectorDB?: (vectorDB: VectorDBType) => void;
  onConfigureVectorDB?: (vectorDB: VectorDBType) => void;
}

type DeploymentType = "all" | "saas" | "self-hosted" | "hybrid";

export default function VectorDBView({
  vectorDBs = [],
  setSearch = () => {},
  onEditVectorDB,
  onDeleteVectorDB,
  onConfigureVectorDB,
}: VectorDBViewProps): JSX.Element {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<DeploymentType>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const {
    data: dbVectorDBs,
    isLoading,
    error,
  } = useGetVectorDBCatalogue();


  const getProviderLogo = (provider: string) => {
      const iconSrc = getProviderIcon(provider);
      return (
        <img 
          src={iconSrc} 
          alt={`${provider} icon`} 
          className="h-4 w-4 object-contain"
        />
      );
    };

  const displayVectorDBs = vectorDBs?.length ? vectorDBs : (dbVectorDBs ?? []);

  /* ---------------------------------- Filtering ---------------------------------- */

  const filteredVectorDBs = displayVectorDBs.filter((db) => {
    const matchesFilter =
      filter === "all" ||
      db.deployment.toLowerCase().replace("-", "") === filter.replace("-", "");
    const matchesSearch =
      !searchQuery ||
      db.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      db.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      db.provider.toLowerCase().includes(searchQuery.toLowerCase());

    return matchesFilter && matchesSearch;
  });

  /* ---------------------------------- Debounced Search ---------------------------------- */

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, setSearch]);

  /* ---------------------------------- Helpers ---------------------------------- */



  const getDeploymentBadgeColor = (deployment: string) => {
    const colors: Record<string, string> = {
      SaaS: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
      "Self-hosted":
        "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
      Hybrid:
        "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
    };
    return (
      colors[deployment] ||
      "bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400"
    );
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      connected: "bg-green-500",
      disconnected: "bg-red-500",
      configuring: "bg-yellow-500",
    };
    return colors[status] || "bg-gray-400";
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      connected: "Connected",
      disconnected: "Disconnected",
      configuring: "Configuring",
    };
    return t(labels[status] || status);
  };

  /* ---------------------------------- JSX ---------------------------------- */

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Header - Fixed */}
      <div className="flex flex-shrink-0 items-center justify-between border-b px-8 py-6">
        <div>
          <div className="mb-2 flex items-center gap-3">
            
            <h1 className="text-2xl font-semibold">{t("Vector Database Catalogue")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Manage and configure vector database connections")}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={t("Search vector databases...")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-64 rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>
      </div>

     

      {/* Table - Scrollable */}
      <div className="flex-1 overflow-auto p-8">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <Loading />
          </div>
        ) : (
          <>
            {!!error && (
              <div className="mb-4 rounded-md border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {t("Failed to load vector databases from database.")}
              </div>
            )}
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="w-full">
                <thead className="bg-muted/50">
                  <tr className="border-b border-border">
                    {[
                      "Database Name",
                      "Provider",
                      "Deployment",
                      "Dimensions",
                      "Index Type",
                      "Status",
                      "Vectors",
                    ].map((h) => (
                      <th
                        key={h}
                        className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                      >
                        {t(h)}
                      </th>
                    ))}
                  </tr>
                </thead>

                <tbody className="divide-y divide-border">
                  {filteredVectorDBs.length === 0 ? (
                    <tr>
                      <td
                        colSpan={9}
                        className="px-6 py-12 text-center text-muted-foreground"
                      >
                        {t("No vector databases found matching your criteria")}
                      </td>
                    </tr>
                  ) : (
                    filteredVectorDBs.map((db) => (
                      <tr key={db.id} className="group hover:bg-muted/50">
                        {/* Database Name */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <div className="font-semibold">{db.name}</div>
                            {db.isCustom && (
                              <span className="inline-flex rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                                {t("Custom")}
                              </span>
                            )}
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {db.description}
                          </div>
                        </td>

                        {/* Provider */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <div className="flex h-8 w-8 items-center justify-center rounded border">
                              {getProviderLogo(db.provider)}
                            </div>
                            <span className="text-sm">{t(db.provider)}</span>
                          </div>
                        </td>

                        {/* Deployment */}
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${getDeploymentBadgeColor(db.deployment)}`}
                          >
                            {t(db.deployment)}
                          </span>
                        </td>

                        {/* Dimensions */}
                        <td className="px-6 py-4">
                          <span className="text-sm text-muted-foreground">
                            {db.dimensions}
                          </span>
                        </td>

                        {/* Index Type */}
                        <td className="px-6 py-4">
                          <span className="text-sm font-mono text-muted-foreground">
                            {db.indexType}
                          </span>
                        </td>

                        {/* Status */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <span
                              className={`h-2 w-2 rounded-full ${getStatusColor(db.status)}`}
                            ></span>
                            <span className="text-sm">
                              {getStatusLabel(db.status)}
                            </span>
                          </div>
                        </td>

                        {/* Vector Count */}
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-1">
                            <Activity className="h-3 w-3 text-muted-foreground" />
                            <span className="text-sm font-medium">
                              {db.vectorCount}
                            </span>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="mt-6 text-center text-sm text-muted-foreground">
              {t("Showing {{shown}} of {{total}} vector databases", {
                shown: filteredVectorDBs.length,
                total: displayVectorDBs.length,
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
