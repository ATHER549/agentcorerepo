import { type DragEventHandler, forwardRef, useRef, useState } from "react";
import IconComponent, {
  ForwardedIconComponent,
} from "@/components/common/genericIconComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { convertTestName } from "@/components/common/storeCardComponent/utils/convert-test-name";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select-custom";
import useDeleteAgent from "@/hooks/agents/use-delete-agent";
import { useAddComponent } from "@/hooks/use-add-component";
import { useDarkStore } from "@/stores/darkStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import type { APIClassType } from "@/types/api";
import { useTranslation } from 'react-i18next';
import {
  createAgentComponent,
  downloadNode,
  getNodeId,
} from "@/utils/reactFlowUtils";
import { cn, removeCountFromString } from "@/utils/utils";

export const SidebarDraggableComponent = forwardRef(
  (
    {
      sectionName,
      display_name,
      icon,
      itemName,
      error,
      color,
      onDragStart,
      apiClass,
      official,
      onDelete,
      beta,
      legacy,
      disabled,
      disabledTooltip,
    }: {
      sectionName: string;
      apiClass: APIClassType;
      icon: string;
      display_name: string;
      itemName: string;
      error: boolean;
      color: string;
      onDragStart: DragEventHandler<HTMLDivElement>;
      official: boolean;
      onDelete?: () => void;
      beta: boolean;
      legacy: boolean;
      disabled?: boolean;
      disabledTooltip?: string;
    },
    ref,
  ) => {
    const [open, setOpen] = useState(false);
    const { deleteAgent } = useDeleteAgent();
    const agents = useAgentsManagerStore((state) => state.agents);
    const addComponent = useAddComponent();
    const { t } = useTranslation();
    const version = useDarkStore((state) => state.version);
    const [cursorPos, setCursorPos] = useState({ x: 0, y: 0 });
    const popoverRef = useRef<HTMLDivElement>(null);

    const handlePointerDown = (e) => {
      if (!open) {
        const rect = popoverRef.current?.getBoundingClientRect() ?? {
          left: 0,
          top: 0,
        };
        setCursorPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
      }
    };

    function handleSelectChange(value: string) {
      switch (value) {
        case "download": {
          const type = removeCountFromString(itemName);
          downloadNode(
            createAgentComponent(
              { id: getNodeId(type), type, node: apiClass },
              version,
            ),
          );
          break;
        }
        case "delete": {
          if (onDelete) {
            onDelete();
            break;
          }
          const agentId = agents?.find((f) => f.name === display_name);
          if (agentId) deleteAgent({ id: agentId.id });
          break;
        }
      }
    }

    const handleKeyDown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        e.stopPropagation();
        addComponent(apiClass, itemName);
      }
    };

    return (
      <Select
        onValueChange={handleSelectChange}
        onOpenChange={(change) => setOpen(change)}
        open={open}
        key={itemName}
      >
        <ShadTooltip
          content={disabled ? disabledTooltip : null}
          styleClasses="z-50"
        >
          <div
            onPointerDown={handlePointerDown}
            onContextMenuCapture={(e) => {
              e.preventDefault();
              setOpen(true);
            }}
            key={itemName}
            data-tooltip-id={itemName}
            tabIndex={0}
            onKeyDown={handleKeyDown}
            className="rounded-md outline-none ring-ring focus-visible:ring-1"
            data-testid={`${sectionName.toLowerCase()}_${display_name.toLowerCase()}_draggable`}
          >
            <div
              data-testid={sectionName + display_name}
              id={sectionName + display_name}
              className={cn(
                "group/draggable flex cursor-grab items-center gap-2 rounded-md bg-muted p-1 px-2 hover:bg-secondary-hover/75",
                error && "cursor-not-allowed select-none",
                disabled
                  ? "pointer-events-none bg-accent text-placeholder-foreground h-8"
                  : "bg-muted text-foreground",
              )}
              draggable={!error}
              style={{
                borderLeftColor: color,
              }}
              onDragStart={onDragStart}
              onDoubleClick={() => {
                if (!disabled) {
                  addComponent(apiClass, itemName);
                }
              }}
              onDragEnd={() => {
                if (
                  document.getElementsByClassName("cursor-grabbing").length > 0
                ) {
                  document.body.removeChild(
                    document.getElementsByClassName("cursor-grabbing")[0],
                  );
                }
              }}
            >
              <ForwardedIconComponent
                name={icon}
                className="h-[18px] w-[18px] shrink-0"
              />
              <div className="flex flex-1 items-center overflow-hidden">
                <ShadTooltip content={display_name} styleClasses="z-50">
                  <span
                    data-testid="display-name"
                    className="truncate text-sm font-normal"
                  >
                    {t(display_name)}
                  </span>
                </ShadTooltip>
                {beta && (
                  <Badge
                    variant="pinkStatic"
                    size="xq"
                    className="ml-1.5 shrink-0"
                  >
                    {t("Beta")}
                  </Badge>
                )}
                {legacy && (
                  <Badge
                    variant="secondaryStatic"
                    size="xq"
                    className="ml-1.5 shrink-0"
                  >
                    {t("Legacy")}
                  </Badge>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {!disabled && (
                  <Button
                    data-testid={`add-component-button-${convertTestName(
                      display_name,
                    )}`}
                    variant="ghost"
                    size="icon"
                    tabIndex={-1}
                    className="text-primary"
                    onClick={() => addComponent(apiClass, itemName)}
                  >
                    <ForwardedIconComponent
                      name="Plus"
                      className="h-4 w-4 shrink-0 transition-all group-hover/draggable:opacity-100 group-focus/draggable:opacity-100 sm:opacity-0"
                    />
                  </Button>
                )}
                <div ref={popoverRef}>
                  <ForwardedIconComponent
                    name="GripVertical"
                    className="h-4 w-4 shrink-0 text-muted-foreground group-hover/draggable:text-primary"
                  />
                  <SelectTrigger tabIndex={-1}></SelectTrigger>
                  <SelectContent
                    position="popper"
                    side="bottom"
                    sideOffset={-25}
                    style={{
                      position: "absolute",
                      left: cursorPos.x,
                      top: cursorPos.y,
                    }}
                  >
                    <SelectItem value={"download"}>
                      <div className="flex">
                        <IconComponent
                          name="Download"
                          className="relative top-0.5 mr-2 h-4 w-4"
                        />{" "}
                        {t("Download")}{" "}
                      </div>{" "}
                    </SelectItem>
                    {(!official || onDelete) && (
                      <SelectItem
                        value={"delete"}
                        data-testid="draggable-component-menu-delete"
                      >
                        <div className="flex">
                          <IconComponent
                            name="Trash2"
                            className="relative top-0.5 mr-2 h-4 w-4"
                          />{" "}
                          {t("Delete")}{" "}
                        </div>{" "}
                      </SelectItem>
                    )}
                  </SelectContent>
                </div>
              </div>
            </div>
          </div>
        </ShadTooltip>
      </Select>
    );
  },
);

export default SidebarDraggableComponent;
