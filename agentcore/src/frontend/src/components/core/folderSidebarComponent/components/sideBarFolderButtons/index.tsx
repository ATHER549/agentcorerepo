import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useContext } from "react";
import { useLocation, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { AuthContext } from "@/contexts/authContext";
import { SidebarRail, SidebarTrigger } from "@/components/ui/sidebar";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { DEFAULT_FOLDER } from "@/constants/constants";
import { useUpdateUser } from "@/controllers/API/queries/auth";
import {
  usePatchFolders,
  usePostFolders,
  usePostUploadFolders,
} from "@/controllers/API/queries/folders";
import { useGetDownloadFolders } from "@/controllers/API/queries/folders/use-get-download-folders";
import { CustomStoreButton } from "@/customization/components/custom-store-button";
import {
  ENABLE_CUSTOM_PARAM,
  ENABLE_AGENTCORE,
  ENABLE_FILE_MANAGEMENT,
  ENABLE_KNOWLEDGE_BASES,
  ENABLE_MCP_NOTICE,
} from "@/customization/feature-flags";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { track } from "@/customization/utils/analytics";
import { customGetDownloadFolderBlob } from "@/customization/utils/custom-get-download-folders";
import { createFileUpload } from "@/helpers/create-file-upload";
import { getObjectsFromFilelist } from "@/helpers/get-objects-from-filelist";
import useUploadAgent from "@/hooks/agents/use-upload-agent";
import { useIsMobile } from "@/hooks/use-mobile";
import useAuthStore from "@/stores/authStore";
import type { FolderType } from "../../../../../pages/MainPage/entities";
import useAlertStore from "../../../../../stores/alertStore";
import useAgentsManagerStore from "../../../../../stores/agentsManagerStore";
import { useFolderStore } from "../../../../../stores/foldersStore";
import { handleKeyDown } from "../../../../../utils/reactFlowUtils";
import { cn } from "../../../../../utils/utils";
import useFileDrop from "../../hooks/use-on-file-drop";
import { SidebarFolderSkeleton } from "../sidebarFolderSkeleton";
import { HeaderButtons } from "./components/header-buttons";
import { InputEditFolderName } from "./components/input-edit-folder-name";
import { MCPServerNotice } from "./components/mcp-server-notice";
import { SelectOptions } from "./components/select-options";

// Import your logos here
// import FullLogo from "@/assets/full-logo.svg"; // Your full logo when expanded
// import CollapsedLogo from "@/assets/collapsed-logo.svg"; // Your icon/small logo when collapsed

type SideBarFoldersButtonsComponentProps = {
  handleChangeFolder?: (id: string) => void;
  handleDeleteFolder?: (item: FolderType) => void;
  handleFilesClick?: () => void;
};
const SideBarFoldersButtonsComponent = ({
  handleChangeFolder,
  handleDeleteFolder,
  handleFilesClick,
}: SideBarFoldersButtonsComponentProps) => {
  const { t } = useTranslation();
  const location = useLocation();
  const pathname = location.pathname;
  const folders = useFolderStore((state) => state.folders);
  const loading = !folders;
  const refInput = useRef<HTMLInputElement>(null);

  const _navigate = useCustomNavigate();
  
  // Get sidebar state to detect if it's collapsed
  const { open: sidebarOpen } = useSidebar();

  const currentFolder = pathname.split("/");
  const urlWithoutPath =
    pathname.split("/").length < (ENABLE_CUSTOM_PARAM ? 5 : 4);
  const checkPathFiles = pathname.includes("assets");

  const checkPathName = (itemId: string) => {
    if (urlWithoutPath && itemId === myCollectionId && !checkPathFiles) {
      return true;
    }
    return currentFolder.includes(itemId);
  };

  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const isMobile = useIsMobile({ maxWidth: 1024 });
  const folderIdDragging = useFolderStore((state) => state.folderIdDragging);
  const myCollectionId = useFolderStore((state) => state.myCollectionId);
  const takeSnapshot = useAgentsManagerStore((state) => state.takeSnapshot);
  const { permissions, role } = useContext(AuthContext);

  const folderId = useParams().folderId ?? myCollectionId ?? "";

  const { dragOver, dragEnter, dragLeave, onDrop } = useFileDrop(folderId);
  const uploadAgent = useUploadAgent();
  const [foldersNames, setFoldersNames] = useState({});
  const [editFolders, setEditFolderName] = useState(
    folders.map((obj) => ({ name: obj.name, edit: false })) ?? [],
  );

  const isFetchingFolders = !!useIsFetching({
    queryKey: ["useGetFolders"],
    exact: false,
  });

  const { mutate: mutateDownloadFolder } = useGetDownloadFolders({});
  const { mutate: mutateAddFolder, isPending } = usePostFolders();
  const { mutate: mutateUpdateFolder } = usePatchFolders();
  const { mutate } = usePostUploadFolders();

  const checkHoveringFolder = (folderId: string) => {
    if (folderId === folderIdDragging) {
      return "bg-accent text-accent-foreground";
    }
  };

  const isFetchingFolder = !!useIsFetching({
    queryKey: ["useGetFolder"],
    exact: false,
  });

  const isDeletingFolder = !!useIsMutating({
    mutationKey: ["useDeleteFolders"],
  });

  const isUpdatingFolder =
    isFetchingFolders ||
    isFetchingFolder ||
    isPending ||
    loading ||
    isDeletingFolder;

  const handleUploadAgentsToFolder = () => {
    createFileUpload().then((files: File[]) => {
      if (files?.length === 0) {
        return;
      }

      getObjectsFromFilelist<any>(files).then((objects) => {
        if (objects.every((agent) => agent.data?.nodes)) {
          uploadAgent({ files }).then(() => {
            setSuccessData({
              title: "Uploaded successfully",
            });
          });
        } else {
          files.forEach((folder) => {
            const formData = new FormData();
            formData.append("file", folder);
            mutate(
              { formData },
              {
                onSuccess: () => {
                  setSuccessData({
                    title: "Project uploaded successfully.",
                  });
                },
                onError: (err) => {
                  console.error(err);
                  setErrorData({
                    title: `Error on uploading your project, try dragging it into an existing project.`,
                    list: [err["response"]["data"]["message"]],
                  });
                },
              },
            );
          });
        }
      });
    });
  };

  const handleDownloadFolder = (id: string, folderName: string) => {
    mutateDownloadFolder(
      {
        folderId: id,
      },
      {
        onSuccess: (response) => {
          customGetDownloadFolderBlob(response, id, folderName, setSuccessData);
        },
        onError: (e) => {
          setErrorData({
            title: `An error occurred while downloading your project.`,
          });
        },
      },
    );
  };

  function addNewFolder() {
    mutateAddFolder(
      {
        data: {
          name: "New Project",
          parent_id: null,
          description: "",
        },
      },
      {
        onSuccess: (folder) => {
          track("Create New Project");
          handleChangeFolder!(folder.id);
        },
      },
    );
  }

  function handleEditFolderName(e, name): void {
    const {
      target: { value },
    } = e;
    setFoldersNames((old) => ({
      ...old,
      [name]: value,
    }));
  }

  useEffect(() => {
    if (folders && folders.length > 0) {
      setEditFolderName(
        folders.map((obj) => ({ name: obj.name, edit: false })),
      );
    }
  }, [folders]);

  const handleEditNameFolder = async (item) => {
    const newEditFolders = editFolders.map((obj) => {
      if (obj.name === item.name) {
        return { name: item.name, edit: false };
      }
      return { name: obj.name, edit: false };
    });
    setEditFolderName(newEditFolders);
    if (foldersNames[item.name].trim() !== "") {
      setFoldersNames((old) => ({
        ...old,
        [item.name]: foldersNames[item.name],
      }));
      const body = {
        ...item,
        name: foldersNames[item.name],
        agents: item.agents?.length > 0 ? item.agents : [],
        components: item.components?.length > 0 ? item.components : [],
      };

      mutateUpdateFolder(
        {
          data: body,
          folderId: item.id!,
        },
        {
          onSuccess: (updatedFolder) => {
            const updatedFolderIndex = folders.findIndex(
              (f) => f.id === updatedFolder.id,
            );

            const updateFolders = [...folders];
            updateFolders[updatedFolderIndex] = updatedFolder;

            setFoldersNames({});
            setEditFolderName(
              folders.map((obj) => ({
                name: obj.name,
                edit: false,
              })),
            );
          },
        },
      );
    } else {
      setFoldersNames((old) => ({
        ...old,
        [item.name]: item.name,
      }));
    }
  };

  const handleDoubleClick = (event, item) => {
    if (item.name === DEFAULT_FOLDER) {
      return;
    }

    event.stopPropagation();
    event.preventDefault();

    handleSelectFolderToRename(item);
  };

  const handleSelectFolderToRename = (item) => {
    if (!foldersNames[item.name]) {
      setFoldersNames({ [item.name]: item.name });
    }

    if (editFolders.find((obj) => obj.name === item.name)?.name) {
      const newEditFolders = editFolders.map((obj) => {
        if (obj.name === item.name) {
          return { name: item.name, edit: true };
        }
        return { name: obj.name, edit: false };
      });
      setEditFolderName(newEditFolders);
      takeSnapshot();
      return;
    }

    setEditFolderName((old) => [...old, { name: item.name, edit: true }]);
    setFoldersNames((oldFolder) => ({
      ...oldFolder,
      [item.name]: item.name,
    }));
    takeSnapshot();
  };

  const handleKeyDownFn = (e, item) => {
    if (e.key === "Escape") {
      const newEditFolders = editFolders.map((obj) => {
        if (obj.name === item.name) {
          return { name: item.name, edit: false };
        }
        return { name: obj.name, edit: false };
      });
      setEditFolderName(newEditFolders);
      setFoldersNames({});
      setEditFolderName(
        folders.map((obj) => ({
          name: obj.name,
          edit: false,
        })),
      );
    }
    if (e.key === "Enter") {
      refInput.current?.blur();
    }
  };

  const [hoveredFolderId, setHoveredFolderId] = useState<string | null>(null);

  const userData = useAuthStore((state) => state.userData);
  const { mutate: updateUser } = useUpdateUser();
  const userDismissedMcpDialog = userData?.optins?.mcp_dialog_dismissed;

  const [isDismissedMcpDialog, setIsDismissedMcpDialog] = useState(
    userDismissedMcpDialog,
  );

  const can = (permissionKey: string) => permissions?.includes(permissionKey);

  // Dispatch custom event when sidebar state changes
  useEffect(() => {
    const event = new CustomEvent("sidebar-state-change", {
      detail: { open: sidebarOpen }
    });
    window.dispatchEvent(event);
  }, [sidebarOpen]);

  const handleDismissMcpDialog = () => {
    setIsDismissedMcpDialog(true);
    updateUser({
      user_id: userData?.id!,
      user: {
        optins: {
          ...userData?.optins,
          mcp_dialog_dismissed: true,
        },
      },
    });
  };

  const handleFilesNavigation = () => {
    _navigate("/assets/files");
  };

  const handleKnowledgeNavigation = () => {
    _navigate("/assets/knowledge-bases");
  };

  return (
    <Sidebar
      collapsible={isMobile ? "offcanvas" : "icon"}
      data-testid="project-sidebar"
      className="bg-[var(--sidebar-background)] text-[var(--sidebar-foreground)]"
    >
      {/* ================= HEADER ================= */}
      <div
        className="absolute top-[56px] right-[-12px] z-50 -translate-y-1/2"
      >
        <SidebarTrigger
          className="h-6 w-6 rounded-full bg-background border shadow-md hover:bg-accent"
        />
      </div>
      <SidebarHeader className="flex h-12 items-center px-3">
        {/* Logo changes based on sidebar collapse state */}
        
      </SidebarHeader>

      {/* ================= CONTENT ================= */}
      <SidebarContent className="text-[var(--sidebar-foreground)]">
  <SidebarGroup className="p-4 py-2">
    <SidebarGroupContent>
      <SidebarMenu className="text-[var(--sidebar-foreground)]">

        {/* Dashboard */}
        {can("view_dashboard") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/dashboard-admin")}
              onClick={() => _navigate("/dashboard-admin")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="LayoutDashboard"
                className="h-4 w-4"
              />
              {t("Dashboard")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Projects */}
        {can("view_projects_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/agents")}
              onClick={() => _navigate("/agents")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="FolderKanban"
                className="h-4 w-4"
              />
              {t("Projects")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Review & Approval */}
        {can("view_approval_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/approval")}
              onClick={() => _navigate("/approval")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="ClipboardCheck"
                className="h-4 w-4"
              />
              {t("Review & Approval")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Agent Registry */}
        {can("view_published_agents") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/agent-catalogue")}
              onClick={() => _navigate("/agent-catalogue")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Bot"
                className="h-4 w-4"
              />
              {t("Agent Registry")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Model Registry */}
        {can("view_models") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/model-catalogue")}
              onClick={() => _navigate("/model-catalogue")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Database"
                className="h-4 w-4"
              />
              {t("Model Registry")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Agent Runtime */}
        {can("view_control_panel") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/workflows")}
              onClick={() => _navigate("/workflows")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="PlayCircle"
                className="h-4 w-4"
              />
              {t("Agent Control Panel")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Automations */}
        <SidebarMenuItem>
          <SidebarMenuButton
            size="md"
            isActive={pathname.startsWith("/scheduler")}
            onClick={() => _navigate("/scheduler")}
            className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
          >
            <ForwardedIconComponent
              name="Zap"
              className="h-4 w-4"
            />
            {t("Agent Scheduler")}
          </SidebarMenuButton>
        </SidebarMenuItem>

        {/* Orchestrator */}
        {can("view_orchastration_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/orchestrator-chat")}
              onClick={() => _navigate("/orchestrator-chat")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="GitBranch"
                className="h-4 w-4"
              />
              {t("Orchestration Chat")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Observability */}
        {can("view_observability_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/observability-dashboard")}
              onClick={() => _navigate("/observability-dashboard")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Activity"
                className="h-4 w-4"
              />
              {t("Observability")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Evaluation */}
        {can("view_evaluation_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/evaluation")}
              onClick={() => _navigate("/evaluation")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Scale"
                className="h-4 w-4"
              />
              {t("Evaluation")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {can("view_guardrail_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/guardrails")}
              onClick={() => _navigate("/guardrails")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="ShieldCheck"
                className="h-4 w-4"
              />
              {t("Guardrails Catalogue")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {can("view_vectordb_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/vector-db")}
              onClick={() => _navigate("/vector-db")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Database"
                className="h-4 w-4"
              />
              {t("VectorDB Catalogue")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {(can("connectore_page") || can("view_connectors_page") || can("connector_page")) && (
          <SidebarMenuItem>
              <SidebarMenuButton
                size="md"
                isActive={pathname.startsWith("/connectors")}
                onClick={() => _navigate("/connectors")}
                className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
              >
                <ForwardedIconComponent
                  name="Cable"
                  className="h-4 w-4"
                />
                Connectors
              </SidebarMenuButton>
            </SidebarMenuItem>
        )}

        {can("view_mcp_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/mcp-servers")}
              onClick={() => _navigate("/mcp-servers")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Server"
                className="h-4 w-4"
              />
              {t("MCP Servers")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Timeout Settings */}
        {can("view_knowledge_base") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/assets/knowledge-bases")}
              onClick={() => _navigate("/assets/knowledge-bases")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="BookOpen"
                className="h-4 w-4"
              />
              {t("Knowledge Base Management")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {/* Packages */}
        {can("view_packages_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/packages")}
              onClick={() => _navigate("/packages")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Package"
                className="h-4 w-4"
              />
              {t("Packages")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {role === "root" && can("view_platform_configs") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/timeout-settings")}
              onClick={() => _navigate("/timeout-settings")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Clock"
                className="h-4 w-4"
              />
              {t("Platform Configurations")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

        {can("view_help_support_page") && (
          <SidebarMenuItem>
            <SidebarMenuButton
              size="md"
              isActive={pathname.startsWith("/help-support") || pathname.startsWith("/settings/help-support")}
              onClick={() => _navigate("/help-support")}
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="CircleHelp"
                className="h-4 w-4"
              />
              {t("Help & Support")}
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}

      </SidebarMenu>
    </SidebarGroupContent>
  </SidebarGroup>
</SidebarContent>



      {/* ================= FOOTER ================= */}
      {/* <SidebarFooter className="border-t">
        <div className="grid w-full items-center gap-2 p-2">
          {can("view_settings_page") && (
            <SidebarMenuButton
              onClick={() => _navigate("/settings")}
              size="md"
              className="text-[var(--sidebar-foreground)] hover:!bg-[var(--button-primary)] hover:!text-[var(--tabs-label)] data-[active=true]:!bg-[var(--button-primary)] data-[active=true]:!text-[var(--tabs-label)] transition-colors"
            >
              <ForwardedIconComponent
                name="Settings"
                className="h-4 w-4"
              />
              Settings
            </SidebarMenuButton>
          )}
        </div>
      </SidebarFooter> */}
    </Sidebar>
  );
};
export default SideBarFoldersButtonsComponent;
