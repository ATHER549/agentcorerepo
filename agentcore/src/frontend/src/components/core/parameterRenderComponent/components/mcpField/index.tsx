import { useEffect, useMemo, useRef, useState } from "react";
import { useAddMCPServer } from "@/controllers/API/queries/mcp/use-add-mcp-server";
import { useGetMCPServers } from "@/controllers/API/queries/mcp/use-get-mcp-servers";
import AddMcpServerModal from "@/modals/mcpServerModal";
import useAlertStore from "@/stores/alertStore";
import ListSelectionComponent from "../../../../../CustomNodes/GenericNode/components/ListSelectionComponent";
import { cn } from "../../../../../utils/utils";
import { default as ForwardedIconComponent } from "../../../../common/genericIconComponent";
import { Button } from "../../../../ui/button";
import type { InputProps } from "../../types";

export default function McpComponent({
  value,
  disabled,
  handleOnNewValue,
  editNode = false,
  id = "",
}: InputProps<string, any>): JSX.Element {
  const { data: mcpServers } = useGetMCPServers({ active_only: true });
  const { mutate: addMcpServer } = useAddMCPServer();
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const options = useMemo(
    () =>
      mcpServers?.map((server) => ({
        name: server.server_name,
        description: server.description || server.mode?.toUpperCase() || "",
      })),
    [mcpServers],
  );
  const [open, setOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState<any[]>([]);
  const { name, config } = useMemo(
    () => value ?? { name: "", config: {} },
    [value],
  );

  // Initialize selected item from value on mount or value/options change
  const selectedOption = useMemo(
    () =>
      name
        ? (options?.find((option) => option.name === name) ?? { name: null })
        : null,
    [name, options],
  );

  useEffect(() => {
    if (!options) return;
    const selectedOption = name
      ? options?.find((option) => option.name === name)
      : null;

    if (
      name !== selectedOption?.name &&
      Object.keys(config ?? {}).length === 0
    ) {
      setSelectedItem(
        selectedOption ? [{ name: selectedOption.name }] : [{ name: "" }],
      );
      handleOnNewValue(
        { value: { name: "", config: {} } },
        { skipSnapshot: true },
      );
      return;
    }
    setSelectedItem([{ name }]);
  }, [name, options]);

  const handleSuccess = (server: string) => {
    handleOnNewValue({ value: { name: server, config: {} } });
    setOpen(false);
  };

  const handleSaveButtonClick = () => {
    addMcpServer(
      {
        name,
        ...(config ?? {}),
      },
      {
        onSuccess: () => {
          handleSuccess(name);
        },
        onError: (error) => {
          setErrorData({
            title: "Error adding MCP server",
            list: [error.message],
          });
        },
      },
    );
  };

  const handleRemoveButtonClick = () => {
    handleOnNewValue({ value: { name: "", config: {} } });
  };

  // Handle selection from dialog
  const handleSelection = (item: any) => {
    setSelectedItem([{ name: item.name }]);
    handleOnNewValue(
      { value: { name: item.name, config: {} } },
      { skipSnapshot: true },
    );
    setOpen(false);
  };

  const handleOpenListSelectionDialog = () => {
    setOpen(true);
  };
  const handleCloseListSelectionDialog = () => setOpen(false);

  const handleAddButtonClick = () => {
    setAddOpen(true);
  };

  const showSaveButton = useMemo(() => {
    return (
      !selectedOption?.name &&
      Object.keys(config ?? {}).length > 0 &&
      options !== null
    );
  }, [selectedOption, config]);

  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex w-full gap-2">
        <Button
          variant={!showSaveButton ? "primary" : "secondary"}
          size="xs"
          role="combobox"
          onClick={
            !showSaveButton
              ? handleOpenListSelectionDialog
              : handleRemoveButtonClick
          }
          className={cn(
            !showSaveButton
              ? "dropdown-component-outline input-edit-node"
              : "",
            "w-full py-2",
          )}
          data-testid="mcp-server-dropdown"
          disabled={disabled || !options}
        >
          <div
            className={cn(
              "flex w-full items-center justify-start text-sm font-normal",
            )}
          >
            <span className="truncate">
              {!options
                ? "Loading servers..."
                : selectedItem[0]?.name
                  ? selectedItem[0]?.name
                  : "Choose a server..."}
            </span>
            <ForwardedIconComponent
              name={!showSaveButton ? "ChevronsUpDown" : "X"}
              className="ml-auto h-5 w-5 text-muted-foreground"
            />
          </div>
        </Button>
        {showSaveButton && (
          <Button
            variant="primary"
            size="iconMd"
            className="px-2.5"
            onClick={handleSaveButtonClick}
            data-testid="save-mcp-server-button"
          >
            <ForwardedIconComponent
              name="Save"
              className="h-5 w-5 text-muted-foreground"
            />
          </Button>
        )}
      </div>
      {options && (
        <>
          <ListSelectionComponent
            open={open}
            onClose={handleCloseListSelectionDialog}
            onSelection={handleSelection}
            setSelectedList={setSelectedItem}
            selectedList={selectedItem}
            options={options}
            limit={1}
            id={id}
            value={name}
            editNode={editNode}
            headerSearchPlaceholder="Find a server..."
            handleOnNewValue={handleOnNewValue}
            disabled={disabled}
            addButtonText="Register MCP Server"
            onAddButtonClick={handleAddButtonClick}
          />
          <AddMcpServerModal
            open={addOpen}
            setOpen={setAddOpen}
            onSuccess={handleSuccess}
          />
        </>
      )}
    </div>
  );
}
