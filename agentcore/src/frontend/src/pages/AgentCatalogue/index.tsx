import { Copy, Eye, Search, Star } from "lucide-react";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AuthContext } from "@/contexts/authContext";
import { api } from "@/controllers/API/api";
import { getURL } from "@/controllers/API/helpers/constants";
import { useGetFoldersQuery } from "@/controllers/API/queries/folders/use-get-folders";
import {
  useGetRegistry,
  useGetRegistryRatings,
  usePostRegistryClone,
  usePostRegistryRate,
  type RegistryEntry,
} from "@/controllers/API/queries/registry";
import CustomLoader from "@/customization/components/custom-loader";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useAlertStore from "@/stores/alertStore";

interface AgentCatalogueViewProps {
  setSearch?: (search: string) => void;
}

export default function AgentCatalogueView({
  setSearch,
}: AgentCatalogueViewProps): JSX.Element {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEntry, setSelectedEntry] = useState<RegistryEntry | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [ratingOpen, setRatingOpen] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [cloneName, setCloneName] = useState("");
  const [createProject, setCreateProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDescription, setNewProjectDescription] = useState("");
  const [score, setScore] = useState(5);
  const [review, setReview] = useState("");

  const { permissions } = useContext(AuthContext);
  const navigate = useCustomNavigate();
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);

  const { data: registryData, isLoading: isLoadingRegistry } = useGetRegistry(
    {
      search: searchQuery || undefined,
      page: 1,
      page_size: 60,
      deployment_env: "PROD",
    },
    {
      refetchInterval: 30000,
      keepPreviousData: true,
    },
  );
  const { data: folders = [], refetch: refetchFolders } = useGetFoldersQuery({
    staleTime: 0,
  });
  const { data: ratingsData, refetch: refetchRatings } = useGetRegistryRatings(
    { registry_id: selectedEntry?.id || "" },
    { enabled: ratingOpen && !!selectedEntry?.id },
  );
  const cloneMutation = usePostRegistryClone();
  const rateMutation = usePostRegistryRate();

  const filteredAgents = useMemo(
    () => registryData?.items || [],
    [registryData?.items],
  );

  useEffect(() => {
    if (!setSearch) return;
    const timer = setTimeout(() => setSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, setSearch]);

  useEffect(() => {
    if (!selectedProjectId && folders.length > 0) {
      setSelectedProjectId(String(folders[0].id || ""));
    }
  }, [folders, selectedProjectId]);

  const openCloneModal = (entry: RegistryEntry) => {
    setSelectedEntry(entry);
    setCloneOpen(true);
    setCloneName(`${entry.title} (Copy)`);
    setCreateProject(false);
    setNewProjectName("");
    setNewProjectDescription("");
  };

  const openRatingModal = (entry: RegistryEntry) => {
    setSelectedEntry(entry);
    setRatingOpen(true);
    setScore(5);
    setReview("");
  };

  const handleClone = async () => {
    try {
      if (!selectedEntry) return;
      let projectId = selectedProjectId;
      if (createProject) {
        if (!newProjectName.trim()) {
          setErrorData({ title: t("Project name is required") });
          return;
        }
        const created = await api.post(`${getURL("PROJECTS")}/`, {
          name: newProjectName.trim(),
          description: newProjectDescription.trim(),
          agents_list: [],
          components_list: [],
        });
        projectId = String(created?.data?.id || "");
        const refreshed = await refetchFolders();
        if (!projectId) {
          const updatedFolders = refreshed?.data || folders;
          const fallback = updatedFolders.find(
            (f) => f.name === newProjectName.trim(),
          );
          projectId = String(fallback?.id || "");
        }
      }
      if (!projectId) {
        setErrorData({ title: t("Please select a project first") });
        return;
      }
      const response = await cloneMutation.mutateAsync({
        registry_id: selectedEntry.id,
        project_id: projectId,
        new_name: cloneName.trim() || undefined,
      });
      setSuccessData({
        title: t("Agent '{{name}}' copied successfully", {
          name: response.agent_name,
        }),
      });
      setCloneOpen(false);
      navigate(`/agent/${response.agent_id}/folder/${projectId}`);
    } catch (error: any) {
      setErrorData({
        title: t("Failed to copy agent"),
        list: [error?.response?.data?.detail || t("Please try again")],
      });
    }
  };

  const handleRate = async () => {
    try {
      if (!selectedEntry) return;
      await rateMutation.mutateAsync({
        registry_id: selectedEntry.id,
        score,
        review: review.trim() || undefined,
      });
      await refetchRatings();
      setSuccessData({ title: t("Rating submitted successfully") });
    } catch (error: any) {
      setErrorData({
        title: t("Failed to submit rating"),
        list: [error?.response?.data?.detail || t("Please try again")],
      });
    }
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex flex-shrink-0 items-center justify-between border-b px-8 py-6">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{t("Agent Registry")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t(
              "Discover and deploy pre-built AI agents and workflows. Clone, customize, and integrate into your applications.",
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              placeholder={t("Search agents")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-64 rounded-lg border bg-card py-2.5 pl-10 pr-4 text-sm"
            />
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8">
        {isLoadingRegistry ? (
          <div className="flex h-full items-center justify-center">
            <CustomLoader />
          </div>
        ) : filteredAgents.length === 0 ? (
          <div className="rounded-lg border border-border bg-card p-12 text-center">
            <p className="text-muted-foreground">{t("No registry agents found")}</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {filteredAgents.map((agent) => (
                <div
                  key={agent.id}
                  className="group relative overflow-hidden rounded-lg border bg-card transition-all hover:border-primary/50"
                >
                  <div className="p-6">
                    <div className="mb-4 flex items-start gap-4">
                      <div className="min-w-0 flex-1">
                        <h3 className="mb-1 truncate text-lg font-semibold">
                          {agent.title}
                        </h3>
                        <p className="text-xs text-muted-foreground">
                          {t("by")} {agent.listed_by_username || t("Unknown")}
                        </p>
                      </div>
                    </div>

                    <p className="mb-4 line-clamp-2 text-sm text-muted-foreground">
                      {agent.summary || t("No description available.")}
                    </p>

                    <div className="mb-4 flex flex-wrap gap-2">
                      {(agent.tags || []).map((tag: string, idx: number) => (
                        <span
                          key={`${agent.id}-${idx}`}
                          className="rounded-md border bg-muted px-2.5 py-1 text-xs"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>

                    <div className="flex items-center justify-between border-t pt-4">
                      <ShadTooltip
                        content={
                          !can("copy_agents")
                            ? t("You don't have permission to view ratings")
                            : t("Click to rate and view reviews")
                        }
                      >
                        <button
                          type="button"
                          onClick={() =>
                            can("copy_agents") && openRatingModal(agent)
                          }
                          className={`flex items-center gap-1.5 text-sm ${!can("copy_agents") ? "cursor-not-allowed opacity-50" : ""}`}
                          disabled={!can("copy_agents")}
                        >
                          <Star className="h-4 w-4 fill-yellow-500 text-yellow-500" />
                          <span className="font-medium">
                            {Number(agent.rating || 0).toFixed(1)}
                          </span>
                          <span className="text-muted-foreground">
                            ({agent.rating_count || 0})
                          </span>
                        </button>
                      </ShadTooltip>

                      <div className="flex items-center gap-2">
                        <ShadTooltip
                          content={
                            !can("view_only_agent")
                              ? t("You don't have permission to view")
                              : ""
                          }
                        >
                          <span className="inline-block">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={!can("view_only_agent")}
                              onClick={() =>
                                navigate(`/agent-catalogue/${agent.id}/view`)
                              }
                            >
                              <Eye className="mr-1.5 h-3.5 w-3.5" />
                              {t("View")}
                            </Button>
                          </span>
                        </ShadTooltip>

                        <ShadTooltip
                          content={
                            !can("copy_agents")
                              ? t("You don't have permission to copy")
                              : ""
                          }
                        >
                          <span className="inline-block">
                            <Button
                              size="sm"
                              disabled={!can("copy_agents")}
                              onClick={() => openCloneModal(agent)}
                            >
                              <Copy className="mr-1.5 h-3.5 w-3.5" />
                              {t("Copy")}
                            </Button>
                          </span>
                        </ShadTooltip>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-6 text-center text-sm text-muted-foreground">
              {t("Showing {{shown}} of {{total}} agents", {
                shown: filteredAgents.length,
                total: registryData?.total || 0,
              })}
            </div>
          </>
        )}
      </div>

      <Dialog open={cloneOpen} onOpenChange={setCloneOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("Copy Agent")}</DialogTitle>
            <DialogDescription>
              {t(
                "Choose existing project or create a new project, then copy this registry agent.",
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 text-sm">
            <label className="block">
              <span className="mb-1 block text-xs text-muted-foreground">
                {t("Agent Name")}
              </span>
              <input
                value={cloneName}
                onChange={(e) => setCloneName(e.target.value)}
                className="w-full rounded-md border bg-card px-3 py-2"
                placeholder={t("Copied agent name")}
              />
            </label>

            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={createProject}
                onChange={(e) => setCreateProject(e.target.checked)}
              />
              <span>{t("Create new project and copy there")}</span>
            </label>

            {createProject ? (
              <div className="space-y-2">
                <input
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  className="w-full rounded-md border bg-card px-3 py-2"
                  placeholder={t("New project name")}
                />
                <textarea
                  value={newProjectDescription}
                  onChange={(e) => setNewProjectDescription(e.target.value)}
                  className="w-full rounded-md border bg-card px-3 py-2"
                  placeholder={t("New project description (optional)")}
                />
              </div>
            ) : (
              <select
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                className="w-full rounded-md border bg-card px-3 py-2"
              >
                <option value="">{t("Select project")}</option>
                {folders.map((folder) => (
                  <option
                    key={folder.id || folder.name}
                    value={String(folder.id || "")}
                  >
                    {folder.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCloneOpen(false)}>
              {t("Cancel")}
            </Button>
            <Button onClick={handleClone} disabled={cloneMutation.isLoading}>
              {cloneMutation.isLoading ? t("Copying...") : t("Copy Agent")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={ratingOpen} onOpenChange={setRatingOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("Rate Agent")}</DialogTitle>
            <DialogDescription>
              {t("Submit your rating and review for this registry agent.")}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 text-sm">
            <div>
              <span className="mb-1 block text-xs text-muted-foreground">
                {t("Score (1 to 5)")}
              </span>
              <input
                type="number"
                min={1}
                max={5}
                step={0.5}
                value={score}
                onChange={(e) => setScore(Number(e.target.value))}
                className="w-full rounded-md border bg-card px-3 py-2"
              />
            </div>
            <textarea
              value={review}
              onChange={(e) => setReview(e.target.value)}
              className="w-full rounded-md border bg-card px-3 py-2"
              placeholder={t("Write a short review (optional)")}
            />

            <div className="rounded-md border bg-muted/30 p-3">
              <p className="text-xs text-muted-foreground">
                {t("Average:")}{" "}
                {Number(
                  ratingsData?.average_rating || selectedEntry?.rating || 0,
                ).toFixed(1)}{" "}
                | {t("Total ratings:")} 
                {ratingsData?.total_ratings || selectedEntry?.rating_count || 0}
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRatingOpen(false)}>
              {t("Close")}
            </Button>
            <Button onClick={handleRate} disabled={rateMutation.isLoading}>
              {rateMutation.isLoading ? t("Submitting...") : t("Submit Rating")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
