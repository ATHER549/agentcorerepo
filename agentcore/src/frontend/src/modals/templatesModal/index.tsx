import { useParams } from "react-router-dom";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { track } from "@/customization/utils/analytics";
import useAddAgent from "@/hooks/agents/use-add-agent";
import { useFolderStore } from "@/stores/foldersStore";
import type { newAgentModalPropsType } from "../../types/components";
import BaseModal from "../baseModal";
import TemplateContentComponent from "./components/TemplateContentComponent";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";

export default function TemplatesModal({
  open,
  setOpen,
}: newAgentModalPropsType): JSX.Element {
  const addAgent = useAddAgent();
  const navigate = useCustomNavigate();
  const { folderId } = useParams();
  const myCollectionId = useFolderStore((state) => state.myCollectionId);
  const folders = useFolderStore((state) => state.folders);

  const { permissions } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const canCreateAgent =
    can("edit_agents") ||
    can("view_projects_page") ||
    can("view_project_page");
  const hasValidProject =
    Boolean(folderId) ||
    Boolean(
      myCollectionId &&
        folders?.some((folder) => folder.id === myCollectionId),
    );

  const createBlankAgent = async (projectId?: string) => {
    const id = await addAgent({ projectId });
    if (!id) return;
    const targetFolderId = projectId ?? folderId;
    navigate(`/agent/${id}${targetFolderId ? `/folder/${targetFolderId}` : ""}`);
    track("New Agent Created", { template: "Blank Agent" });
  };

  const handleBlankAgentClick = async () => {
    if (!hasValidProject) {
      setOpen(false);
      navigate("/agents?openCreateProject=1");
      return;
    }

    try {
      await createBlankAgent();
    } catch {}
  };

  return (
    <BaseModal size="templates" open={open} setOpen={setOpen} className="p-0">
      <BaseModal.Content className="flex flex-col p-0 h-full overflow-hidden">
        <div className="flex h-full flex-col">
          <main className="flex flex-1 flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto p-6 md:gap-8 custom-scrollbar">
              <div className="mb-6">
                <h2 className="text-2xl font-semibold">All Templates</h2>
              </div>
              <TemplateContentComponent
                currentTab="all-templates"
                categories={[
                  { title: "All templates", icon: "LayoutPanelTop", id: "all-templates" },
                ]}
              />
            </div>
            <BaseModal.Footer className="border-t bg-background">
              <div className="flex w-full flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center">
                <div className="flex flex-col items-start justify-center">
                  <div className="font-semibold">Start from scratch</div>
                  <div className="text-sm text-muted-foreground">
                    Begin with a fresh agent to build from scratch.
                  </div>
                </div>
                 {canCreateAgent && (
                <Button
                  onClick={handleBlankAgentClick}
                  size="sm"
                  data-testid="blank-agent"
                  className="shrink-0"
                >
                  <ForwardedIconComponent
                    name="Plus"
                    className="h-4 w-4 shrink-0"
                  />
                  {hasValidProject ? "Blank Agent" : "Create Project First"}
                </Button>
                 )}
              </div>
            </BaseModal.Footer>
          </main>
        </div>
      </BaseModal.Content>
      
      <style>{`
        .custom-scrollbar {
          scrollbar-width: thin;
          scrollbar-color: transparent transparent;
          transition: scrollbar-color 0.3s ease;
        }

        .custom-scrollbar:hover {
          scrollbar-color: rgba(155, 155, 155, 0.5) transparent;
        }

        .custom-scrollbar::-webkit-scrollbar {
          width: 8px;
        }

        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }

        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: transparent;
          border-radius: 4px;
          transition: background-color 0.3s ease;
        }

        .custom-scrollbar:hover::-webkit-scrollbar-thumb {
          background-color: rgba(155, 155, 155, 0.5);
        }

        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background-color: rgba(155, 155, 155, 0.7);
        }
      `}</style>
    </BaseModal>
  );
}
