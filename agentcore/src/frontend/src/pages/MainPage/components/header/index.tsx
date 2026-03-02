import { debounce } from "lodash";
import { useCallback, useEffect, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useDeleteDeleteAgents } from "@/controllers/API/queries/agents/use-delete-delete-agents";
import { useGetDownloadAgents } from "@/controllers/API/queries/agents/use-get-download-agents";
import DeleteConfirmationModal from "@/modals/deleteConfirmationModal";
import useAlertStore from "@/stores/alertStore";
import { cn } from "@/utils/utils";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";

interface HeaderComponentProps {
  agentType: "agents" | "components" | "mcp";
  setAgentType: (agentType: "agents" | "components" | "mcp") => void;
  view: "list" | "grid";
  setView: (view: "list" | "grid") => void;
  setNewProjectModal: (newProjectModal: boolean) => void;
  folderName?: string;
  setSearch: (search: string) => void;
  isEmptyFolder: boolean;
  selectedAgents: string[];
}

const HeaderComponent = ({
  folderName = "",
  agentType,
  setAgentType,
  view,
  setView,
  setNewProjectModal,
  setSearch,
  isEmptyFolder,
  selectedAgents,
}: HeaderComponentProps) => {
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  // Debounce the setSearch function from the parent
  const debouncedSetSearch = useCallback(
    debounce((value: string) => {
      setSearch(value);
    }, 1000),
    [setSearch],
  );

  const { mutate: downloadAgents, isPending: isDownloading } =
    useGetDownloadAgents();
  const { mutate: deleteAgents, isPending: isDeleting } = useDeleteDeleteAgents();

  const { permissions } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const canCreateAgent =
    can("edit_agents") ||
    can("view_projects_page") ||
    can("view_project_page");

  useEffect(() => {
    debouncedSetSearch(debouncedSearch);

    return () => {
      debouncedSetSearch.cancel(); // Cleanup on unmount
    };
  }, [debouncedSearch, debouncedSetSearch]);

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    setDebouncedSearch(e.target.value);
  };

  const tabTypes = ["components", "agents"];

  const handleDownload = () => {
    downloadAgents({ ids: selectedAgents });
    setSuccessData({ title: "Agents downloaded successfully" });
  };

  const handleDelete = () => {
    deleteAgents(
      { agent_ids: selectedAgents },
      {
        onSuccess: () => {
          setSuccessData({ title: "Agents deleted successfully" });
        },
      },
    );
  };

  return (
    <>
      <div
        className="flex items-center pb-4 text-sm font-medium"
        data-testid="mainpage_title"
      >
        <div className="h-7 w-10 transition-all group-data-[open=true]/sidebar-wrapper:md:w-0 lg:hidden">
          <div className="relative left-0 opacity-100 transition-all group-data-[open=true]/sidebar-wrapper:md:opacity-0">
            <SidebarTrigger>
              <ForwardedIconComponent
                name="PanelLeftOpen"
                aria-hidden="true"
                className=""
              />
            </SidebarTrigger>
          </div>
        </div>
        {folderName}
      </div>
      {!isEmptyFolder && (
        <>
          <div className={cn("flex flex-row-reverse pb-4")}>
            <div className="w-full border-b dark:border-border" />
            
          </div>
          {/* Search and filters */}
          {agentType !== "mcp" && (
            <div className="flex justify-between">
              <div className="flex w-full xl:w-5/12">
                <Input
                  icon="Search"
                  data-testid="search-store-input"
                  type="text"
                  placeholder={`Search ${agentType}...`}
                  className="mr-2 !text-mmd"
                  inputClassName="!text-mmd"
                  value={debouncedSearch}
                  onChange={handleSearch}
                />
                <div className="relative mr-2 flex h-fit rounded-lg border border-muted bg-muted">
                  {/* Sliding Indicator */}
                  <div
                    className={`absolute top-[2px] h-[32px] w-8 transform rounded-md bg-background shadow-md transition-transform duration-300 ${
                      view === "list"
                        ? "left-[2px] translate-x-0"
                        : "left-[6px] translate-x-full"
                    }`}
                  ></div>

                  {/* Buttons */}
                  {["list", "grid"].map((viewType) => (
                    <Button
                      key={viewType}
                      unstyled
                      size="icon"
                      className={`group relative z-10 m-[2px] flex-1 rounded-lg p-2 ${
                        view === viewType
                          ? "text-foreground"
                          : "text-muted-foreground hover:bg-muted"
                      }`}
                      onClick={() => setView(viewType as "list" | "grid")}
                    >
                      <ForwardedIconComponent
                        name={viewType === "list" ? "Menu" : "LayoutGrid"}
                        aria-hidden="true"
                        className="h-4 w-4 group-hover:text-foreground"
                      />
                    </Button>
                  ))}
                </div>
              </div>
              <div className="flex items-center">
                <div
                  className={cn(
                    "flex w-0 items-center gap-2 overflow-hidden opacity-0 transition-all duration-300",
                    selectedAgents.length > 0 && "w-36 opacity-100",
                  )}
                >
                  <Button
                    variant="outline"
                    size="iconMd"
                    className="h-8 w-8"
                    data-testid="download-bulk-btn"
                    onClick={handleDownload}
                    loading={isDownloading}
                  >
                    <ForwardedIconComponent name="Download" />
                  </Button>

                  <DeleteConfirmationModal
                    onConfirm={handleDelete}
                    description={"agent" + (selectedAgents.length > 1 ? "s" : "")}
                    note={
                      "and " +
                      (selectedAgents.length > 1 ? "their" : "its") +
                      " message history"
                    }
                  >
                    <Button
                      variant="destructive"
                      size="iconMd"
                      className="px-2.5 !text-mmd"
                      data-testid="delete-bulk-btn"
                      loading={isDeleting}
                    >
                      <ForwardedIconComponent name="Trash2" />
                      Delete
                    </Button>
                  </DeleteConfirmationModal>
                </div>
                {canCreateAgent && (
                <ShadTooltip content="New Agent" side="bottom">
                  <Button
                    variant="default"
                    size="iconMd"
                    className="z-50 px-2.5 !text-mmd"
                    onClick={() => setNewProjectModal(true)}
                    id="new-project-btn"
                    data-testid="new-project-btn"
                  >
                    <ForwardedIconComponent
                      name="Plus"
                      aria-hidden="true"
                      className="h-4 w-4"
                    />
                    <span className="hidden whitespace-nowrap font-semibold md:inline">
                      New Agent
                    </span>
                  </Button>
                </ShadTooltip>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
};

export default HeaderComponent;
