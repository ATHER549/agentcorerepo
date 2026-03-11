import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import useAlertStore from "@/stores/alertStore";
import type { AgentType } from "@/types/agent";
import useDuplicateAgent from "../../hooks/use-handle-duplicate";
import useSelectOptionsChange from "../../hooks/use-select-options-change";

type DropdownComponentProps = {
  agentData: AgentType;
  setOpenDelete: (open: boolean) => void;
  handleExport: () => void;
  handleEdit: () => void;
  canModifyAgent: boolean;
};

const DropdownComponent = ({
  agentData,
  setOpenDelete,
  handleExport,
  handleEdit,
  canModifyAgent,
}: DropdownComponentProps) => {
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const { handleDuplicate } = useDuplicateAgent({ agent: agentData });

  const duplicateAgent = () => {
    handleDuplicate().then(() =>
      setSuccessData({
        title: `${agentData.is_component ? "Component" : "agent"} duplicated successfully`,
      }),
    );
  };

  const { handleSelectOptionsChange } = useSelectOptionsChange(
    [agentData.id],
    setErrorData,
    setOpenDelete,
    handleExport,
    duplicateAgent,
    handleEdit,
  );

  return (
    <>
      {canModifyAgent && (
        <DropdownMenuItem
          onClick={(e) => {
            e.stopPropagation();
            handleSelectOptionsChange("edit");
          }}
          className="cursor-pointer"
          data-testid="btn-edit-agent"
        >
          <ForwardedIconComponent
            name="SquarePen"
            aria-hidden="true"
            className="mr-2 h-4 w-4"
          />
          Edit details
        </DropdownMenuItem>
      )}
      {/* <DropdownMenuItem
        onClick={(e) => {
          e.stopPropagation();
          handleSelectOptionsChange("export");
        }}
        className="cursor-pointer"
        data-testid="btn-download-json"
      >
        <ForwardedIconComponent
          name="Download"
          aria-hidden="true"
          className="mr-2 h-4 w-4"
        />
        Export
      </DropdownMenuItem> */}
      <DropdownMenuItem
        onClick={(e) => {
          e.stopPropagation();
          handleSelectOptionsChange("duplicate");
        }}
        className="cursor-pointer"
        data-testid="btn-duplicate-agent"
      >
        <ForwardedIconComponent
          name="CopyPlus"
          aria-hidden="true"
          className="mr-2 h-4 w-4"
        />
        Duplicate
      </DropdownMenuItem>
      {canModifyAgent && (
        <DropdownMenuItem
          onClick={(e) => {
            e.stopPropagation();
            setOpenDelete(true);
          }}
          className="cursor-pointer text-destructive"
          data-testid="btn_delete_dropdown_menu"
        >
          <ForwardedIconComponent
            name="Trash2"
            aria-hidden="true"
            className="mr-2 h-4 w-4"
          />
          Delete
        </DropdownMenuItem>
      )}
    </>
  );
};

export default DropdownComponent;
