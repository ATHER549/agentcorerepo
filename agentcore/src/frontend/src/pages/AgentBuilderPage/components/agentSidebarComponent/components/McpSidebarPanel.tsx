import ShadTooltip from "@/components/common/shadTooltipComponent";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
} from "@/components/ui/sidebar";
import type { APIClassType } from "@/types/api";
import { removeCountFromString } from "@/utils/utils";
import { SearchConfigTrigger } from "./searchConfigTrigger";
import SidebarDraggableComponent from "./sidebarDraggableComponent";
import { useTranslation } from 'react-i18next';
import { CustomLink } from "@/customization/components/custom-link";

type McpSidebarGroupProps = {
  mcpComponents?: any[];
  nodeColors: any;
  onDragStart: (
    event: React.DragEvent<any>,
    data: { type: string; node?: APIClassType },
  ) => void;
  openCategories: string[];
  mcpLoading?: boolean;
  mcpSuccess?: boolean;
  search: string;
  hasMcpServers: boolean;
  showSearchConfigTrigger: boolean;
  showConfig: boolean;
  setShowConfig: React.Dispatch<React.SetStateAction<boolean>>;
};

const McpSidebarGroup = ({
  mcpComponents,
  nodeColors,
  onDragStart,
  openCategories,
  mcpLoading,
  mcpSuccess,
  search,
  hasMcpServers,
  showSearchConfigTrigger,
  showConfig,
  setShowConfig,
}: McpSidebarGroupProps) => {
  const isLoading = mcpLoading;
  const isSuccess = mcpSuccess;
  const { t } = useTranslation();

  const categoryName = "MCP";
  const isOpen = search === "" || openCategories.includes(categoryName);

  if (!isOpen) {
    return null;
  }

  return (
    <SidebarGroup className={`p-3 ${!hasMcpServers ? " h-full" : ""}`}>
      {hasMcpServers && (
        <SidebarGroupLabel className="cursor-default w-full flex items-center justify-between">
          <span>{t("MCP Servers")}</span>
          {showSearchConfigTrigger && (
            <SearchConfigTrigger
              showConfig={showConfig}
              setShowConfig={setShowConfig}
            />
          )}
        </SidebarGroupLabel>
      )}
      <SidebarGroupContent className="h-full">
        <SidebarMenu className={!hasMcpServers ? " h-full" : ""}>
          {isLoading && <span>{t("Loading...")}</span>}
          {isSuccess && !hasMcpServers && (
            <McpEmptyState />
          )}
          {isSuccess &&
            mcpComponents &&
            hasMcpServers &&
            mcpComponents.map((mcpComponent) => (
              <ShadTooltip
                content={mcpComponent.display_name || mcpComponent.name}
                side="right"
                key={mcpComponent.mcpServerName ?? mcpComponent.display_name}
              >
                <SidebarDraggableComponent
                  sectionName={"mcp"}
                  apiClass={mcpComponent}
                  icon={mcpComponent.icon ?? "Mcp"}
                  onDragStart={(event) =>
                    onDragStart(event, {
                      type: removeCountFromString("MCP"),
                      node: mcpComponent,
                    })
                  }
                  color={nodeColors["agents"]}
                  itemName={"MCP"}
                  error={!!mcpComponent.error}
                  display_name={t(mcpComponent.mcpServerName ?? mcpComponent.display_name)}
                  official={mcpComponent.official === false ? false : true}
                  beta={mcpComponent.beta ?? false}
                  legacy={mcpComponent.legacy ?? false}
                  disabled={false}
                  disabledTooltip={""}
                />
              </ShadTooltip>
            ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
};

const McpEmptyState = () => {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col h-full w-full items-center justify-center py-8 px-4 text-center min-h-[200px]">
      <p className="text-muted-foreground mb-2">{t("No MCP Servers Registered")}</p>
      <p className="text-xs text-muted-foreground">
        {t("Manage MCP servers from the")}{" "}
        <CustomLink className="underline" to="/settings/mcp-servers">
          {t("MCP Servers page")}
        </CustomLink>
        .
      </p>
    </div>
  );
};

export default McpSidebarGroup;
