import { useContext, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import { SidebarMenuButton, useSidebar } from "@/components/ui/sidebar";
import { AuthContext } from "@/contexts/authContext";
import { ENABLE_NEW_SIDEBAR } from "@/customization/feature-flags";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import AddMcpServerModal from "@/modals/mcpServerModal";

import { useTranslation } from 'react-i18next';

const SidebarMenuButtons = ({
  customComponent,
  addComponent,
  isLoading = false,
}) => {
  const { activeSection } = useSidebar();
  const { permissions } = useContext(AuthContext);
  const can = (permissionKey: string) => permissions?.includes(permissionKey);
  const canAddMcp = can("add_new_mcp");
  const canRequestMcp = can("request_new_mcp");
  const [addMcpOpen, setAddMcpOpen] = useState(false);
  const [requestMcpOpen, setRequestMcpOpen] = useState(false);
  const navigate = useCustomNavigate();
  const { t } = useTranslation();
  const handleAddMcpServerClick = () => {
    setAddMcpOpen(true);
  };

  return ENABLE_NEW_SIDEBAR && activeSection === "mcp" ? (
    <>
      {canAddMcp && (
        <SidebarMenuButton asChild>
          <Button
            unstyled
            disabled={isLoading}
            onClick={handleAddMcpServerClick}
            data-testid="sidebar-add-mcp-server-button"
            className="flex items-center w-full h-full gap-3 hover:bg-muted"
          >
            <ForwardedIconComponent
              name="Plus"
              className="h-4 w-4 text-muted-foreground"
            />
            <span className="group-data-[state=open]/collapsible:font-semibold">
              {t("Add MCP Server")}
            </span>
          </Button>
        </SidebarMenuButton>
      )}
      {!canAddMcp && canRequestMcp && (
        <SidebarMenuButton asChild>
          <Button
            unstyled
            disabled={isLoading}
            onClick={() => setRequestMcpOpen(true)}
            data-testid="sidebar-request-mcp-server-button"
            className="flex items-center w-full h-full gap-3 hover:bg-muted"
          >
            <ForwardedIconComponent
              name="Plus"
              className="h-4 w-4 text-muted-foreground"
            />
            <span className="group-data-[state=open]/collapsible:font-semibold">
              {t("Request MCP Server")}
            </span>
          </Button>
        </SidebarMenuButton>
      )}
      <SidebarMenuButton asChild>
        <Button
          unstyled
          disabled={isLoading}
          onClick={() => {
            navigate("/settings/mcp-servers");
          }}
          data-testid="sidebar-manage-servers-button"
          className="flex items-center w-full h-full gap-3 hover:bg-muted"
        >
          <ForwardedIconComponent
            name="ArrowUpRight"
            className="h-4 w-4 text-muted-foreground"
          />
          <span className="group-data-[state=open]/collapsible:font-semibold">
            {t("Manage Servers")}
          </span>
        </Button>
      </SidebarMenuButton>
      <AddMcpServerModal open={addMcpOpen} setOpen={setAddMcpOpen} />
      <AddMcpServerModal open={requestMcpOpen} setOpen={setRequestMcpOpen} requestMode />
    </>
  ) : (
    <SidebarMenuButton asChild className="group">
      <Button
        unstyled
        disabled={isLoading}
        onClick={() => {
          if (customComponent) {
            addComponent(customComponent, "CustomComponent");
          }
        }}
        data-testid="sidebar-custom-component-button"
        className="flex items-center w-full h-full gap-3 hover:bg-muted"
      >
        <ForwardedIconComponent
          name="Plus"
          className="h-4 w-4 text-muted-foreground"
        />
        <span className="group-data-[state=open]/collapsible:font-semibold">
          {t("Code Editor Component")}
        </span>
      </Button>
    </SidebarMenuButton>
  );
};

export default SidebarMenuButtons;

