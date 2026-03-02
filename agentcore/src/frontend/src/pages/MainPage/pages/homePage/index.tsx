import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import PaginatorComponent from "@/components/common/paginatorComponent";
import CardsWrapComponent from "@/components/core/cardsWrapComponent";
import { IS_MAC } from "@/constants/constants";
import { useGetFolderQuery } from "@/controllers/API/queries/folders/use-get-folder";
import { CustomBanner } from "@/customization/components/custom-banner";
import {
  ENABLE_AGENTCORE,
} from "@/customization/feature-flags";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useFolderStore } from "@/stores/foldersStore";
import HeaderComponent from "../../components/header";
import ListComponent from "../../components/list";
import ListSkeleton from "../../components/listSkeleton";
import ModalsComponent from "../../components/modalsComponent";
import useFileDrop from "../../hooks/use-on-file-drop";
import EmptyFolder from "../emptyFolder";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";

const HomePage = ({ type }: { type: "agents" | "components" | "mcp" }) => {
  const [view, setView] = useState<"grid" | "list">(() => {
    const savedView = localStorage.getItem("view");
    return savedView === "grid" || savedView === "list" ? savedView : "list";
  });
  const [newProjectModal, setNewProjectModal] = useState(false);
  const { folderId } = useParams();
  const [pageIndex, setPageIndex] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [search, setSearch] = useState("");
  const navigate = useCustomNavigate();

  const { permissions, role } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);

  const [agentType, setAgentType] = useState<"agents" | "components" | "mcp">(
    type,
  );
  const myCollectionId = useFolderStore((state) => state.myCollectionId);
  const folders = useFolderStore((state) => state.folders);
  const folderName =
    folders.find((folder) => folder.id === folderId)?.name ??
    folders[0]?.name ??
    "";

  useEffect(() => {
    // Only check if we have a folderId and folders have loaded
    if (folderId && folders && folders.length > 0) {
      const folderExists = folders.find((folder) => folder.id === folderId);
      if (!folderExists) {
        // Folder doesn't exist for this user, redirect to /all
        console.error("Invalid folderId, redirecting to /all");
        navigate("/all");
      }
    }
  }, [folderId, folders, navigate]);

  const { data: folderData, isLoading } = useGetFolderQuery({
    id: folderId ?? myCollectionId!,
    page: pageIndex,
    size: pageSize,
    is_component: agentType === "components",
    is_agent: agentType === "agents",
    search,
  });

  const data = {
    agents: folderData?.agents?.items ?? [],
    name: folderData?.project?.name ?? "",
    description: folderData?.project?.description ?? "",
    parent_id: folderData?.project?.parent_id ?? "",
    components: folderData?.project?.components ?? [],
    pagination: {
      page: folderData?.agents?.page ?? 1,
      size: folderData?.agents?.size ?? 12,
      total: folderData?.agents?.total ?? 0,
      pages: folderData?.agents?.pages ?? 0,
    },
  };

  useEffect(() => {
    localStorage.setItem("view", view);
  }, [view]);

  const handlePageChange = useCallback((newPageIndex, newPageSize) => {
    setPageIndex(newPageIndex);
    setPageSize(newPageSize);
  }, []);

  const onSearch = useCallback((newSearch) => {
    setSearch(newSearch);
    setPageIndex(1);
  }, []);

  // Use the paginated folder data (from GET /projects/{id}) to determine
  // if the folder is empty, rather than the global agents store which may
  // not have loaded yet or may be stale.
  const isEmptyFolder =
    !isLoading &&
    (folderData?.agents?.total ?? 0) === 0 &&
    !search;

  const handleFileDrop = useFileDrop(isEmptyFolder ? undefined : agentType);

  useEffect(() => {
    // If this tab has no items but the other tab does, auto-switch.
    // Use paginated data instead of global store for accuracy.
    if (
      !isEmptyFolder &&
      data.agents.length === 0 &&
      !isLoading
    ) {
      // Current tab is empty, check if we should switch
      setAgentType(agentType === "agents" ? "components" : "agents");
    }
  }, [isEmptyFolder, data.agents.length, isLoading]);

  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number | null>(
    null,
  );
  const [isShiftPressed, setIsShiftPressed] = useState(false);
  const [isCtrlPressed, setIsCtrlPressed] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only track these keys when we're in list/selection mode and not when a modal is open
      // or when an input field is focused
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target instanceof HTMLElement && e.target.isContentEditable)
      ) {
        return;
      }

      if (e.key === "Shift") {
        setIsShiftPressed(true);
      } else if ((!IS_MAC && e.key === "Control") || e.key === "Meta") {
        setIsCtrlPressed(true);
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target instanceof HTMLElement && e.target.isContentEditable)
      ) {
        return;
      }

      if (e.key === "Shift") {
        setIsShiftPressed(false);
      } else if ((!IS_MAC && e.key === "Control") || e.key === "Meta") {
        setIsCtrlPressed(false);
      }
    };

    // Reset key states when window loses focus
    const handleBlur = () => {
      setIsShiftPressed(false);
      setIsCtrlPressed(false);
    };

    // Only add listeners if we're in agents or components mode, not MCP mode
    if (agentType === "agents" || agentType === "components") {
      document.addEventListener("keydown", handleKeyDown);
      document.addEventListener("keyup", handleKeyUp);
      window.addEventListener("blur", handleBlur);
    }

    // Clean up event listeners when component unmounts
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("blur", handleBlur);

      // Reset key states on unmount
      setIsShiftPressed(false);
      setIsCtrlPressed(false);
    };
  }, [agentType]);

  const setSelectedAgent = useCallback(
    (selected: boolean, agentId: string, index: number) => {
      setLastSelectedIndex(index);
      if (isShiftPressed && lastSelectedIndex !== null) {
        // Find the indices of the last selected and current agent
        const agents = data.agents;

        // Determine the range to select
        const start = Math.min(lastSelectedIndex, index);
        const end = Math.max(lastSelectedIndex, index);
        // Get all agent IDs in the range
        const agentsToSelect = agents
          .slice(start, end + 1)
          .map((agent) => agent.id);

        // Update selection
        if (selected) {
          setSelectedAgents((prev) =>
            Array.from(new Set([...prev, ...agentsToSelect])),
          );
        } else {
          setSelectedAgents((prev) =>
            prev.filter((id) => !agentsToSelect.includes(id)),
          );
        }
      } else {
        if (selected) {
          setSelectedAgents([...selectedAgents, agentId]);
        } else {
          setSelectedAgents(selectedAgents.filter((id) => id !== agentId));
        }
      }
    },
    [selectedAgents, lastSelectedIndex, data.agents, isShiftPressed],
  );

  useEffect(() => {
    setSelectedAgents((old) =>
      old.filter((id) => data.agents.some((agent) => agent.id === id)),
    );
  }, [folderData?.agents?.items]);

  // Reset key states when navigating away
  useEffect(() => {
    return () => {
      setIsShiftPressed(false);
      setIsCtrlPressed(false);
    };
  }, [folderId]);

  return (
    <CardsWrapComponent
      onFileDrop={handleFileDrop}
      dragMessage={`Drop your ${isEmptyFolder ? "agents or components" : agentType} here`}
    >
      <div
        className="flex h-full w-full flex-col overflow-y-auto"
        data-testid="cards-wrapper"
      >
        <div className="flex h-full w-full flex-col 3xl:container">
          {ENABLE_AGENTCORE && <CustomBanner />}
          <div className="flex flex-1 flex-col justify-start p-4">
            <div className="flex h-full flex-col justify-start">
              <HeaderComponent
                folderName={folderName}
                agentType={agentType}
                setAgentType={setAgentType}
                view={view}
                setView={setView}
                setNewProjectModal={setNewProjectModal}
                setSearch={onSearch}
                isEmptyFolder={isEmptyFolder}
                selectedAgents={selectedAgents}
              />
              {isEmptyFolder ? (
                <EmptyFolder setOpenModal={setNewProjectModal} />
              ) : (
                <div className="flex h-full flex-col">
                  {isLoading ? (
                    view === "grid" ? (
                      <div className="mt-4 grid grid-cols-1 gap-1 md:grid-cols-2 lg:grid-cols-3">
                        <ListSkeleton />
                        <ListSkeleton />
                      </div>
                    ) : (
                      <div className="mt-4 flex flex-col gap-1">
                        <ListSkeleton />
                        <ListSkeleton />
                      </div>
                    )
                  ) : (agentType === "agents" || agentType === "components") &&
                    data &&
                    data.pagination.total > 0 ? (
                    view === "grid" ? (
                      <div className="mt-4 grid grid-cols-1 gap-1 md:grid-cols-2 lg:grid-cols-3">
                        {data.agents.map((agent, index) => (
                          <ListComponent
                            key={agent.id}
                            agentData={agent}
                            index={index}
                            selected={selectedAgents.includes(agent.id)}
                            setSelected={(selected) =>
                              setSelectedAgent(selected, agent.id, index)
                            }
                            shiftPressed={isShiftPressed || isCtrlPressed}
                          />
                        ))}
                      </div>
                    ) : (
                      <div className="mt-4 flex flex-col gap-1">
                        {data.agents.map((agent, index) => (
                          <ListComponent
                            key={agent.id}
                            agentData={agent}
                            index={index}
                            selected={selectedAgents.includes(agent.id)}
                            setSelected={(selected) =>
                              setSelectedAgent(selected, agent.id, index)
                            }
                            shiftPressed={isShiftPressed || isCtrlPressed}
                            disabled={can("view_agents_page") && !can("edit_agents")}
                          />
                        ))}
                      </div>
                    )
                  ) : agentType === "agents" ? (
                    <div className="pt-24 text-center text-sm text-secondary-foreground">
                      No agents in this project.{" "}
                      <a
                        onClick={() => setNewProjectModal(true)}
                        className="cursor-pointer underline"
                      >
                        Create a new agent
                      </a>
                      , or browse the store.
                    </div>
                  ) : (
                    <div className="pt-24 text-center text-sm text-secondary-foreground">
                      No saved or custom components.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          {(agentType === "agents" || agentType === "components") &&
            !isLoading &&
            !isEmptyFolder &&
            data.pagination.total >= 10 && (
              <div className="flex justify-end px-3 py-4">
                <PaginatorComponent
                  pageIndex={data.pagination.page}
                  pageSize={data.pagination.size}
                  rowsCount={[12, 24, 48, 96]}
                  totalRowsCount={data.pagination.total}
                  paginate={handlePageChange}
                  pages={data.pagination.pages}
                  isComponent={agentType === "components"}
                />
              </div>
            )}
        </div>
      </div>

      <ModalsComponent
        openModal={newProjectModal}
        setOpenModal={setNewProjectModal}
        openDeleteFolderModal={false}
        setOpenDeleteFolderModal={() => {}}
        handleDeleteFolder={() => {}}
      />
    </CardsWrapComponent>
  );
};

export default HomePage;
