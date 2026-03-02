import { useEffect, useState } from "react";
import { Plus, Folder, MoreVertical, Edit2, Trash2, Download, FileText, X, Info } from "lucide-react";
import { useFolderStore } from "@/stores/foldersStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { usePostFolders } from "@/controllers/API/queries/folders";
import { useGetDownloadFolders } from "@/controllers/API/queries/folders/use-get-download-folders";
import useAlertStore from "@/stores/alertStore";
import { track } from "@/customization/utils/analytics";
import { customGetDownloadFolderBlob } from "@/customization/utils/custom-get-download-folders";
import type { FolderType } from "@/pages/MainPage/entities";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface FolderCardsViewProps {
  setOpenModal: (open: boolean) => void;
  onFolderClick: (folderId: string) => void;
  onRenameFolder?: (folder: FolderType) => void;
  onDeleteFolder?: (folder: FolderType) => void;
  onFilesClick?: () => void;
}

export default function FolderCardsView({
  setOpenModal,
  onFolderClick,
  onRenameFolder,
  onDeleteFolder,
  onFilesClick,
}: FolderCardsViewProps): JSX.Element {
  const folders = useFolderStore((state) => state.folders);
  const agents = useAgentsManagerStore((state) => state.agents);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [expandedTableRow, setExpandedTableRow] = useState<string | null>(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [selectedFolderDetail, setSelectedFolderDetail] = useState<FolderType | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  
  const { mutate: mutateAddFolder, isPending } = usePostFolders();
  const { mutate: mutateDownloadFolder } = useGetDownloadFolders({});

  const displayFolders = folders || [];
  const { permissions, role } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);

  // Mirror backend ROLE_ALIASES so every role variant resolves identically.
  const ROLE_ALIASES: Record<string, string> = {
    admin: "super_admin",
    super_admin: "super_admin",
    department_admin: "department_admin",
    business_user: "business_user",
    root_admin: "root",
    root: "root",
  };
  const rawNormalized = (role || "").toLowerCase().trim().replace(/\s+/g, "_");
  const normalizedRole = ROLE_ALIASES[rawNormalized] || rawNormalized;

  const showCreatedBy = normalizedRole === "department_admin" || normalizedRole === "super_admin" || normalizedRole === "root";
  const showDepartment = normalizedRole === "super_admin" || normalizedRole === "root";
  const showOrganization = normalizedRole === "root";
  // Filter folders based on search query
  const filteredFolders = displayFolders.filter(folder => 
    folder.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    folder.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );
  
  // Sort by updated_at descending (most recently updated first)
  const sortedFolders = [...filteredFolders].sort((a, b) => {
    if (!a.updated_at || !b.updated_at) return 0;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });
  
  // Split folders into recent (top 4) and older
  const recentFolders = sortedFolders.slice(0, 4);
  const olderFolders = sortedFolders.slice(4);

  // Count agents per folder
  const getAgentCount = (folderId: string) => {
    if (!agents || agents.length === 0) return 0;
    const count = agents.filter((agent) => agent.project_id === folderId).length;
    console.log(`Folder ${folderId} has ${count} agents`);
    return count;
  };

  // Format date
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' });
  };

  // Open create modal
  const handleOpenCreateModal = () => {
    setProjectName("");
    setProjectDescription("");
    setCreateModalOpen(true);
  };

  useEffect(() => {
    const openModalFromEvent = () => {
      setProjectName("");
      setProjectDescription("");
      setCreateModalOpen(true);
    };

    window.addEventListener("open-create-project-modal", openModalFromEvent);

    const url = new URL(window.location.href);
    if (url.searchParams.get("openCreateProject") === "1") {
      openModalFromEvent();
      url.searchParams.delete("openCreateProject");
      const nextSearch = url.searchParams.toString();
      window.history.replaceState(
        {},
        "",
        `${url.pathname}${nextSearch ? `?${nextSearch}` : ""}${url.hash}`,
      );
    }

    return () => {
      window.removeEventListener("open-create-project-modal", openModalFromEvent);
    };
  }, []);

  // Open detail modal
  const handleOpenDetailModal = (folder: FolderType) => {
    setSelectedFolderDetail(folder);
    setDetailModalOpen(true);
  };

  // Handle creating new folder
  const handleCreateNewFolder = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!projectName.trim()) {
      setErrorData({ title: "Project name is required" });
      return;
    }

    mutateAddFolder(
      {
        data: {
          name: projectName.trim(),
          parent_id: null,
          description: projectDescription.trim(),
        },
      },
      {
        onSuccess: (folder) => {
          track("Create New Project");
          setSuccessData({
            title: "Project created successfully.",
          });
          setCreateModalOpen(false);
          setProjectName("");
          setProjectDescription("");
          onFolderClick(folder.id);
        },
        onError: (err) => {
          console.error(err);
          setErrorData({ title: "Failed to create project" });
        },
      },
    );
  };

  const handleDownloadFolder = (folder: FolderType) => {
    mutateDownloadFolder(
      {
        folderId: folder.id!,
      },
      {
        onSuccess: (response) => {
          customGetDownloadFolderBlob(response, folder.id!, folder.name, setSuccessData);
        },
        onError: (e) => {
          setErrorData({
            title: `An error occurred while downloading your project.`,
          });
        },
      },
    );
  };

  return (
    <>
      <div className="flex h-full w-full flex-col overflow-auto bg-background">
        {/* Header */}
        <div className="flex items-center justify-between border-b bg-background px-6 py-4 sticky top-0 z-10">
          <div>
            <h1 className="text-2xl font-semibold">Projects</h1>
            <p className="text-sm text-muted-foreground">
              Start a new project or select an existing one
            </p>
          </div>
          
          <div className="flex items-center gap-3">
            {/* Search Bar */}
            <div className="relative">
              <input
                type="text"
                placeholder="Search projects..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-10 w-64 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {onFilesClick && (
              <Button
                onClick={onFilesClick}
                variant="outline"
                className="gap-2"
              >
                <FileText className="h-4 w-4" />
                My Files
              </Button>
            )}
          </div>
        </div>

        {/* Cards Section - Recent Projects */}
        <div className="border-b bg-muted/30 px-6 py-6">
          <h2 className="mb-4 text-sm font-semibold text-muted-foreground">Recents</h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">

            {/* Create New Project Card*/}
            {can("view_projects_page") && (
            <div
              className="group relative flex flex-col items-center justify-between rounded-lg border-2 border-dashed border-muted-foreground/25 bg-background p-5 transition-all hover:border-primary hover:bg-accent"
            >
              <div className="flex-1 flex items-center justify-center">
                <button
                  onClick={handleOpenCreateModal}
                  disabled={isPending}
                  className="flex h-14 w-14 items-center justify-center rounded-lg bg-primary/10 transition-colors group-hover:bg-primary/20 disabled:opacity-50"
                >
                  <Plus className="h-6 w-6 text-primary" />
                </button>
              </div>
              <span className="text-center text-xs font-medium text-muted-foreground mt-2">Blank project</span>
            </div>
            )}

            {/* Recent Folder Cards*/}
            {recentFolders.map((folder) => {
              const agentCount = getAgentCount(folder.id);
              return (
                <div
                  key={folder.id}
                  className="group relative flex flex-col items-center justify-between rounded-lg border bg-card p-5 transition-all hover:border-primary hover:shadow-md"
                >
                  {/* Top Right Icons - Menu and Info */}
                  <div className="absolute right-2 top-2 z-10 flex gap-1">
                    {/* Info Button - View Full Details */}
                    {can("view_projects_page") && (
                    <button
                      onClick={() => handleOpenDetailModal(folder)}
                      className="flex h-6 w-6 items-center justify-center rounded-md opacity-0 transition-opacity hover:bg-blue-100 group-hover:opacity-100"
                      title="View details"
                    >
                      <Info className="h-3.5 w-3.5 text-[var(--info-foreground)]" />
                    </button>
                    )}

                    {/* Menu Button - Only show if user has edit or delete permissions */}
                    {can("view_projects_page") && (
                    <div className="z-20">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            onClick={(e) => e.stopPropagation()}
                            className="flex h-6 w-6 items-center justify-center rounded-md opacity-0 transition-opacity hover:bg-accent group-hover:opacity-100"
                          >
                            <MoreVertical className="h-3.5 w-3.5" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {can("view_projects_page") && (
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              onRenameFolder?.(folder);
                            }}
                          >
                            <Edit2 className="mr-2 h-4 w-4" />
                            Rename
                          </DropdownMenuItem>
                          )}
                          {can("view_projects_page") && (
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDownloadFolder(folder);
                            }}
                          >
                            <Download className="mr-2 h-4 w-4" />
                            Download
                          </DropdownMenuItem>
                          )}
                          {can("view_projects_page") && (
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteFolder?.(folder);
                            }}
                            className="text-destructive"
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete
                          </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                    )}
                  </div>

                  {/* Clickable card content - Centered */}
                  <button
                    onClick={() => can("view_projects_page") && onFolderClick(folder.id)}
                    disabled={!can("view_projects_page")}
                    className="flex flex-1 flex-col items-center justify-center gap-3 w-full text-center py-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {/* Icon */}
                    <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-primary/10 transition-colors group-hover:bg-primary/20">
                      <Folder className="h-7 w-7 text-primary" />
                    </div>

                    {/* Text Content */}
                    <div className="w-full space-y-1.5">
                      {/* Folder Name */}
                      <p 
                        className="block text-sm font-semibold line-clamp-2 leading-tight"
                      >
                        {folder.name}
                      </p>

                      {/* Description - Show 1 line with ellipsis */}
                      {folder.description && (
                        <p 
                          className="text-xs text-muted-foreground line-clamp-1"
                        >
                          {folder.description}
                        </p>
                      )}
                      {showCreatedBy && (folder.created_by_email || folder.is_own_project) && (
                        <p className="text-[11px] text-muted-foreground line-clamp-1">
                          {folder.is_own_project ? (
                            <>Created by: <span className="font-semibold text-primary">You</span></>
                          ) : (
                            <>Created by: {folder.created_by_email}</>
                          )}
                        </p>
                      )}
                      {showDepartment && folder.department_name && (
                        <p className="text-[11px] text-muted-foreground line-clamp-1">
                          Department: {folder.department_name}
                        </p>
                      )}
                      {showOrganization && folder.organization_name && (
                        <p className="text-[11px] text-muted-foreground line-clamp-1">
                          Organization: {folder.organization_name}
                        </p>
                      )}
                    </div>
                  </button>

                  {/* Stats - Bottom */}
                  <div className="flex flex-col items-center justify-center gap-1 text-xs text-muted-foreground pt-2 border-t border-border/50 w-full">
                    <span>{agentCount} {agentCount === 1 ? "agent" : "agents"}</span>
                    {folder.updated_at && (
                      <span className="text-xs">{formatDate(folder.updated_at)}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Table/List Section - Older Projects */}
        {olderFolders.length > 0 && (
          <div className="flex-1 overflow-auto px-6 py-4">
            <h2 className="mb-4 text-sm font-semibold text-muted-foreground">Earlier</h2>
            
            <div className="rounded-lg border bg-card overflow-hidden">
              {/* Table Header */}
              <div className="grid grid-cols-12 gap-4 border-b bg-muted/50 px-4 py-3 text-xs font-semibold text-muted-foreground sticky top-0">
                <div className="col-span-5 flex items-center gap-2">
                  <Folder className="h-4 w-4" />
                  <span>Name</span>
                </div>
                {showCreatedBy && <div className="col-span-2 flex items-center">Created By</div>}
                {showDepartment && <div className="col-span-2 flex items-center">Department</div>}
                {showOrganization && <div className="col-span-2 flex items-center">Organization</div>}
                <div className="col-span-1"></div>
              </div>

              {/* Table Body */}
              <div className="divide-y">
                {olderFolders.map((folder) => {
                  const agentCount = getAgentCount(folder.id);
                  const isExpanded = expandedTableRow === folder.id;
                  
                  return (
                    <div 
                      key={folder.id}
                      onMouseEnter={() => {
                        if (folder.description) {
                          setExpandedTableRow(folder.id);
                        }
                      }}
                      onMouseLeave={() => {
                        setExpandedTableRow(null);
                      }}
                    >
                      {/* Main Row */}
                      <div
                        className={`group grid grid-cols-12 gap-4 px-4 py-3 transition-colors hover:bg-muted/50 items-center ${can("view_projects_page") ? "cursor-pointer" : "cursor-not-allowed opacity-50"}`}
                        onClick={() => can("view_projects_page") && onFolderClick(folder.id)}
                      >
                        {/* Name Column */}
                        <div className="col-span-5 flex items-center gap-3 min-w-0">
                          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded bg-primary/10">
                            <Folder className="h-4 w-4 text-primary" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-medium text-sm">
                              {folder.name}
                            </p>
                            {folder.description && !isExpanded && (
                              <p className="text-xs text-muted-foreground truncate">
                                {folder.description}
                              </p>
                            )}
                            <p className="text-xs text-muted-foreground mt-1">
                              {agentCount} {agentCount === 1 ? "agent" : "agents"}
                            </p>
                          </div>
                        </div>

                        {showCreatedBy && (
                          <div className="col-span-2 flex items-center text-sm text-muted-foreground">
                            {folder.is_own_project ? (
                              <span className="truncate font-semibold text-primary">You</span>
                            ) : (
                              <span className="truncate">{folder.created_by_email || "--"}</span>
                            )}
                          </div>
                        )}
                        {showDepartment && (
                          <div className="col-span-2 flex items-center text-sm text-muted-foreground">
                            <span className="truncate">{folder.department_name || "--"}</span>
                          </div>
                        )}
                        {showOrganization && (
                          <div className="col-span-2 flex items-center text-sm text-muted-foreground">
                            <span className="truncate">{folder.organization_name || "--"}</span>
                          </div>
                        )}

                        {/* Actions Column - Only show if user has edit or delete permissions */}
                        <div className="col-span-1 flex items-center justify-end">
                          {(can("edit_projects_page") || can("delete_project")) && (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                onClick={(e) => e.stopPropagation()}
                                className="flex h-8 w-8 items-center justify-center rounded-md opacity-0 transition-opacity hover:bg-accent group-hover:opacity-100"
                              >
                                <MoreVertical className="h-4 w-4" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              {can("edit_projects_page") && (
                              <DropdownMenuItem
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onRenameFolder?.(folder);
                                }}
                              >
                                <Edit2 className="mr-2 h-4 w-4" />
                                Rename
                              </DropdownMenuItem>
                              )}
                              {can("edit_projects_page") && (
                              <DropdownMenuItem
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDownloadFolder(folder);
                                }}
                              >
                                <Download className="mr-2 h-4 w-4" />
                                Download
                              </DropdownMenuItem>
                              )}
                              {can("delete_project") && (
                              <DropdownMenuItem
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onDeleteFolder?.(folder);
                                }}
                                className="text-destructive"
                              >
                                <Trash2 className="mr-2 h-4 w-4" />
                                Delete
                              </DropdownMenuItem>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                          )}
                        </div>
                      </div>

                      {/* Expanded Description Row */}
                      {isExpanded && folder.description && (
                        <div className="grid grid-cols-12 gap-4 px-4 py-3 bg-muted/30 border-t">
                          <div className="col-span-12">
                            <p className="text-xs text-muted-foreground break-words whitespace-normal">
                              <span className="font-semibold">Description:</span> {folder.description}
                            </p>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Empty State */}
        {filteredFolders.length === 0 && (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-lg bg-primary/10">
                <Folder className="h-8 w-8 text-primary" />
              </div>
              {searchQuery ? (
                <>
                  <h3 className="mb-2 text-lg font-semibold">No projects found</h3>
                  <p className="mb-4 text-sm text-muted-foreground">
                    No projects match "{searchQuery}"
                  </p>
                  <button
                    onClick={() => setSearchQuery("")}
                    className="text-sm text-primary hover:underline"
                  >
                    Clear search
                  </button>
                </>
              ) : (
                <>
                  <h3 className="mb-2 text-lg font-semibold">No projects yet</h3>
                  <p className="mb-4 text-sm text-muted-foreground">
                    Create your first project to get started
                  </p>
                  <button
                    onClick={handleOpenCreateModal}
                    disabled={isPending}
                    className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Plus className="h-4 w-4" />
                    Create Project
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Create Project Modal */}
      {createModalOpen && (
        <>
          <div
            className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm"
            onClick={() => setCreateModalOpen(false)}
          />

          <div className="fixed left-[50%] top-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%] rounded-lg border border-border bg-card p-6 shadow-lg">
            <div className="mb-6 flex items-start justify-between">
              <div>
                <h2 className="text-xl font-semibold">
                  Create New Project
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Enter a name and description for your project
                </p>
              </div>
              <button
                onClick={() => setCreateModalOpen(false)}
                className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
              >
                <X className="h-5 w-5" />
                <span className="sr-only">Close</span>
              </button>
            </div>

            <form onSubmit={handleCreateNewFolder} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="projectName" className="text-sm font-medium">
                  Project Name <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="projectName"
                  required
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="e.g., Customer Support Workagent"
                  className="bg-background"
                  autoFocus
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="projectDescription" className="text-sm font-medium">
                  Description (Optional)
                </Label>
                <Textarea
                  id="projectDescription"
                  value={projectDescription}
                  onChange={(e) => setProjectDescription(e.target.value)}
                  placeholder="Brief description of your project..."
                  rows={3}
                  className="resize-none bg-background"
                />
              </div>

              <div className="flex items-center gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setCreateModalOpen(false)}
                  className="flex-1"
                  disabled={isPending}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="default"
                  className="flex-1"
                  disabled={isPending}
                >
                  {isPending ? "Creating..." : "Create Project"}
                </Button>
              </div>
            </form>
          </div>
        </>
      )}

      {/* Project Details Modal - ENTERPRISE DESIGN */}
      {detailModalOpen && selectedFolderDetail && (
        <>
          <div
            className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm"
            onClick={() => setDetailModalOpen(false)}
          />

          <div className="fixed left-[50%] top-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%] rounded-lg border border-border bg-card p-6 shadow-lg">
            <div className="mb-6 flex items-start justify-between">
              <div className="flex gap-3 flex-1">
                <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-lg bg-primary/10">
                  <Folder className="h-6 w-6 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <h2 className="text-lg font-semibold break-words">
                    {selectedFolderDetail.name}
                  </h2>
                  <p className="text-xs text-muted-foreground mt-1">
                    {getAgentCount(selectedFolderDetail.id)} {getAgentCount(selectedFolderDetail.id) === 1 ? "agent" : "agents"}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setDetailModalOpen(false)}
                className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
              >
                <X className="h-5 w-5" />
                <span className="sr-only">Close</span>
              </button>
            </div>

            {/* Details Content */}
            <div className="space-y-4 mb-6">
              {/* Ownership Badge */}
              {selectedFolderDetail.is_own_project && showCreatedBy && (
                <div className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                  Own Project
                </div>
              )}

              {selectedFolderDetail.description && (
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2">DESCRIPTION</h3>
                  <p className="text-sm text-card-foreground break-words whitespace-normal leading-relaxed">
                    {selectedFolderDetail.description}
                  </p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2">AGENTS</h3>
                  <p className="text-sm font-medium">
                    {getAgentCount(selectedFolderDetail.id)}
                  </p>
                </div>
                {selectedFolderDetail.updated_at && (
                  <div>
                    <h3 className="text-xs font-semibold text-muted-foreground mb-2">LAST UPDATED</h3>
                    <p className="text-sm font-medium">
                      {formatDate(selectedFolderDetail.updated_at)}
                    </p>
                  </div>
                )}
              </div>

              {/* RBAC Metadata */}
              {showCreatedBy && (selectedFolderDetail.created_by_email || selectedFolderDetail.is_own_project) && (
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2">CREATED BY</h3>
                  <p className="text-sm font-medium">
                    {selectedFolderDetail.is_own_project ? (
                      selectedFolderDetail.created_by_email ? (
                        <><span className="text-primary">You</span> ({selectedFolderDetail.created_by_email})</>
                      ) : (
                        <span className="text-primary">You</span>
                      )
                    ) : (
                      selectedFolderDetail.created_by_email
                    )}
                  </p>
                </div>
              )}
              {showDepartment && selectedFolderDetail.department_name && (
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2">DEPARTMENT</h3>
                  <p className="text-sm font-medium">{selectedFolderDetail.department_name}</p>
                </div>
              )}
              {showOrganization && selectedFolderDetail.organization_name && (
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2">ORGANIZATION</h3>
                  <p className="text-sm font-medium">{selectedFolderDetail.organization_name}</p>
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 pt-4 border-t">
              {can("view_projects_page") && (
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => {
                  setDetailModalOpen(false);
                  onFolderClick(selectedFolderDetail.id);
                }}
              >
                Open Project
              </Button>
              )}
              {(can("edit_projects_page") || can("delete_project")) && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {can("edit_projects_page") && (
                  <DropdownMenuItem
                    onClick={() => {
                      setDetailModalOpen(false);
                      onRenameFolder?.(selectedFolderDetail);
                    }}
                  >
                    <Edit2 className="mr-2 h-4 w-4" />
                    Rename
                  </DropdownMenuItem>
                  )}
                  {can("edit_projects_page") && (
                  <DropdownMenuItem
                    onClick={() => {
                      setDetailModalOpen(false);
                      handleDownloadFolder(selectedFolderDetail);
                    }}
                  >
                    <Download className="mr-2 h-4 w-4" />
                    Download
                  </DropdownMenuItem>
                  )}
                  {can("delete_project") && (
                  <DropdownMenuItem
                    onClick={() => {
                      setDetailModalOpen(false);
                      onDeleteFolder?.(selectedFolderDetail);
                    }}
                    className="text-destructive"
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
