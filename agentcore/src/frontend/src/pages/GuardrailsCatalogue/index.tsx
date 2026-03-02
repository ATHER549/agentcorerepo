import { Edit2, MoreVertical, Plus, Search, Trash2, ArrowLeft } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import Loading from "@/components/ui/loading";
import { AuthContext } from "@/contexts/authContext";
import {
  type GuardrailInfo,
  useDeleteGuardrailCatalogue,
  useGetGuardrailsCatalogue,
} from "@/controllers/API/queries/guardrails";
import useAlertStore from "@/stores/alertStore";
import NvidiaLogo from "@/assets/nvidia_logo.svg?react";
import EditGuardrailModal from "./components/edit-guardrail-modal";
import GuardrailFrameworksList from "./components/guardrail-frameworks-list";

interface GuardrailsViewProps {
  guardrails?: GuardrailInfo[];
  setSearch?: (search: string) => void;
}

interface GuardrailFramework {
  id: string;
  name: string;
  description: string;
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
}

type CategoryType =
  | "all"
  | "content-safety"
  | "jailbreak"
  | "topic-control"
  | "pii-detection";

// Available guardrail frameworks
const GUARDRAIL_FRAMEWORKS: GuardrailFramework[] = [
  {
    id: "nemo-guardrails",
    name: "NeMo Guardrails",
    description: "NVIDIA's NeMo Guardrails framework for LLM safety and moderation with configurable policies",
    icon: NvidiaLogo,
  }
];

export default function GuardrailsView({
  guardrails = [],
  setSearch = () => {},
}: GuardrailsViewProps): JSX.Element {
  const [filter] = useState<CategoryType>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedGuardrail, setSelectedGuardrail] =
    useState<GuardrailInfo | null>(null);
  const [selectedFramework, setSelectedFramework] =
    useState<GuardrailFramework | null>(null);

  const { permissions } = useContext(AuthContext);
  const can = (permission: string) => permissions?.includes(permission);
  const canCreateOrEdit = can("add_guardrails");
  const canDelete = can("retire_guardrails");
  const canManage = canCreateOrEdit || canDelete;

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const selectedFrameworkId =
    selectedFramework?.id === "nemo-guardrails"
      ? "nemo"
      : selectedFramework?.id === "arize-guardrails"
        ? "arize"
        : undefined;
  const { data: dbGuardrails, isLoading, error } = useGetGuardrailsCatalogue(
    { framework: selectedFrameworkId },
  );
  const deleteMutation = useDeleteGuardrailCatalogue();

  const displayGuardrails = guardrails?.length
    ? guardrails
    : (dbGuardrails ?? []);

  const filteredGuardrails = displayGuardrails.filter((guardrail) => {
    // Guardrail provider reflects the backing model provider (e.g. openai/azure),
    // not the guardrail framework. Do not filter by provider in framework view.
    const matchesFilter = filter === "all" || guardrail.category === filter;
    const matchesSearch =
      !searchQuery ||
      guardrail.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      guardrail.description?.toLowerCase().includes(searchQuery.toLowerCase());

    return matchesFilter && matchesSearch;
  });

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, setSearch]);

  const getCategoryLabel = (category: string) => {
    const labels: Record<string, string> = {
      "content-safety": "Content Safety",
      jailbreak: "Jailbreak Prevention",
      "topic-control": "Topic Control",
      "pii-detection": "PII Detection",
    };
    return labels[category] || category;
  };

  const getCategoryBadgeColor = (category: string) => {
    const colors: Record<string, string> = {
      "content-safety":
        "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
      jailbreak:
        "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
      "topic-control":
        "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
      "pii-detection":
        "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
    };
    return (
      colors[category] ||
      "bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400"
    );
  };

  const handleCreateGuardrail = () => {
    setSelectedGuardrail(null);
    setIsEditModalOpen(true);
  };

  const handleSelectFramework = (framework: GuardrailFramework) => {
    setSelectedFramework(framework);
  };

  const handleBackToFrameworks = () => {
    setSelectedFramework(null);
  };

  const handleEditGuardrail = (guardrail: GuardrailInfo) => {
    setSelectedGuardrail(guardrail);
    setIsEditModalOpen(true);
  };

  const handleDeleteGuardrail = async (guardrail: GuardrailInfo) => {
    const shouldDelete = window.confirm(
      `Delete guardrail "${guardrail.name}"?`,
    );
    if (!shouldDelete) return;

    try {
      await deleteMutation.mutateAsync({ id: guardrail.id });
      setSuccessData({ title: `Guardrail "${guardrail.name}" deleted.` });
    } catch {
      setErrorData({ title: "Failed to delete guardrail." });
    }
  };

  return (
    <>
      {!selectedFramework ? (
        <GuardrailFrameworksList
          frameworks={GUARDRAIL_FRAMEWORKS}
          onSelectFramework={handleSelectFramework}
          isLoading={false}
        />
      ) : (
        <div className="flex h-full w-full flex-col overflow-hidden">
          <div className="flex flex-shrink-0 items-center justify-between border-b px-8 py-6">
            <div>
              <div className="mb-2 flex items-center gap-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleBackToFrameworks}
                  className="h-8 w-8 p-0"
                >
                  <ArrowLeft className="h-4 w-4" />
                </Button>
                <h1 className="text-2xl font-semibold">{selectedFramework.name} Policies</h1>
              </div>
              <p className="text-sm text-muted-foreground">
                Manage and configure guardrail policies for {selectedFramework.name}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  placeholder="Search guardrails..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-64 rounded-lg border border-border bg-card py-2.5 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              {canCreateOrEdit && (
                <Button onClick={handleCreateGuardrail}>
                  <Plus className="mr-2 h-4 w-4" />
                  Add Guardrail
                </Button>
              )}
            </div>
          </div>

          <div className="flex-1 overflow-auto p-8">
            {isLoading ? (
              <div className="flex h-full w-full items-center justify-center">
                <Loading />
              </div>
            ) : (
              <>
                {!!error && (
                  <div className="mb-4 rounded-md border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                    Failed to load guardrails from database.
                  </div>
                )}
                <div className="overflow-x-auto rounded-lg border border-border bg-card">
                  <table className="w-full">
                    <thead className="bg-muted/50">
                      <tr className="border-b border-border">
                        {[
                          "Guardrail Name",
                          "Model",
                          "Category",
                          "Status",
                          ...(canManage ? ["Actions"] : []),
                        ].map((h) => (
                          <th
                            key={h}
                            className="px-6 py-4 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>

                    <tbody className="divide-y divide-border">
                      {filteredGuardrails.length === 0 ? (
                        <tr>
                          <td
                            colSpan={canManage ? 5 : 4}
                            className="px-6 py-12 text-center text-muted-foreground"
                          >
                            No guardrails found matching your criteria
                          </td>
                        </tr>
                      ) : (
                        filteredGuardrails.map((guardrail) => (
                          <tr
                            key={guardrail.id}
                            className="group hover:bg-muted/50"
                          >
                            <td className="px-6 py-4">
                              <div className="flex items-center gap-2">
                                <div className="font-semibold">
                                  {guardrail.name}
                                </div>
                                {guardrail.isCustom && (
                                  <span className="inline-flex rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                                    Custom
                                  </span>
                                )}
                              </div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                {guardrail.description}
                              </div>
                              {guardrail.runtimeReady === true && (
                                <div className="mt-1 text-[11px] text-emerald-600 dark:text-emerald-400">
                                  Runtime ready
                                </div>
                              )}
                              {guardrail.runtimeConfig &&
                                guardrail.runtimeReady === false && (
                                  <div className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">
                                    Runtime config incomplete
                                  </div>
                                )}
                            </td>

                            <td className="px-6 py-4">
                              <div className="text-sm font-medium">
                                {guardrail.modelDisplayName ||
                                  guardrail.modelName ||
                                  "Not linked"}
                              </div>
                              {guardrail.modelName &&
                                guardrail.modelDisplayName && (
                                  <div className="mt-1 text-xs text-muted-foreground">
                                    {guardrail.modelName}
                                  </div>
                                )}
                            </td>

                            <td className="px-6 py-4">
                              <span
                                className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${getCategoryBadgeColor(guardrail.category)}`}
                              >
                                {getCategoryLabel(guardrail.category)}
                              </span>
                            </td>

                            <td className="px-6 py-4">
                              <div className="flex items-center gap-2">
                                <span
                                  className={`h-2 w-2 rounded-full ${guardrail.status === "active" ? "bg-green-500" : "bg-gray-400"}`}
                                ></span>
                                <span className="text-sm capitalize">
                                  {guardrail.status}
                                </span>
                              </div>
                            </td>

                            {canManage && (
                              <td className="px-6 py-4">
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <button className="rounded p-1 hover:bg-muted">
                                      <MoreVertical className="h-4 w-4" />
                                    </button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align="end">
                                    {canCreateOrEdit && (
                                      <DropdownMenuItem
                                        onClick={() =>
                                          handleEditGuardrail(guardrail)
                                        }
                                      >
                                        <Edit2 className="mr-2 h-4 w-4" />
                                        Edit
                                      </DropdownMenuItem>
                                    )}
                                    {canDelete && (
                                      <DropdownMenuItem
                                        onClick={() =>
                                          handleDeleteGuardrail(guardrail)
                                        }
                                        className="text-destructive"
                                      >
                                        <Trash2 className="mr-2 h-4 w-4" />
                                        Delete
                                      </DropdownMenuItem>
                                    )}
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="mt-6 text-center text-sm text-muted-foreground">
                  Showing {filteredGuardrails.length} of {displayGuardrails.length}{" "}
                  guardrails
                </div>
              </>
            )}
          </div>

          <EditGuardrailModal
            open={isEditModalOpen}
            onOpenChange={setIsEditModalOpen}
            guardrail={selectedGuardrail}
            frameworkId={selectedFrameworkId}
          />
        </div>
      )}
    </>
  );
}
