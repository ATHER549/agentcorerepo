import type { CustomCellRendererProps } from "ag-grid-react";
import { useMemo } from "react";
import useHandleOnNewValue from "@/CustomNodes/hooks/use-handle-new-value";
import useHandleNodeClass from "@/CustomNodes/hooks/use-handle-node-class";
import { ParameterRenderComponent } from "@/components/core/parameterRenderComponent";
import type { NodeInfoType } from "@/components/core/parameterRenderComponent/types";
import useAuthStore from "@/stores/authStore";
import useAgentStore from "@/stores/agentStore";
import type { APIClassType } from "@/types/api";
import { isTargetHandleConnected } from "@/utils/reactFlowUtils";
import { cn } from "@/utils/utils";

export default function TableNodeCellRender({
  value: { nodeId, parameterId, isTweaks },
}: CustomCellRendererProps) {
  const edges = useAgentStore((state) => state.edges);
  const node = useAgentStore((state) => state.getNode(nodeId));
  const parameter = node?.data?.node?.template?.[parameterId];
  const currentAgent = useAgentStore((state) => state.currentAgent);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const shouldDisplayApiKey = isAuthenticated;

  const disabled = isTargetHandleConnected(
    edges,
    parameterId,
    parameter,
    nodeId,
  );

  const { handleOnNewValue } = useHandleOnNewValue({
    node: node?.data.node as APIClassType,
    nodeId,
    name: parameterId,
    setNode: isTweaks ? () => {} : undefined,
  });

  const { handleNodeClass } = useHandleNodeClass(
    nodeId,
    isTweaks ? () => {} : undefined,
  );

  const nodeInformationMetadata: NodeInfoType = useMemo(() => {
    return {
      agentId: currentAgent?.id ?? "",
      nodeType: node?.data?.type?.toLowerCase() ?? "",
      agentName: currentAgent?.name ?? "",
      isAuth: shouldDisplayApiKey!,
      variableName: parameterId,
    };
  }, [nodeId, shouldDisplayApiKey, parameterId]);

  return (
    parameter && (
      <div
        className={cn(
          "group mx-auto flex h-full max-h-48 w-[300px] items-center justify-center overflow-auto px-1 py-2.5 custom-scroll",
          isTweaks && "pointer-events-none opacity-30",
        )}
      >
        <ParameterRenderComponent
          nodeId={nodeId}
          handleOnNewValue={handleOnNewValue}
          placeholder={parameter.placeholder}
          templateData={parameter}
          name={parameterId}
          templateValue={parameter.value}
          editNode={true}
          handleNodeClass={handleNodeClass}
          nodeClass={node?.data.node}
          disabled={disabled}
          nodeInformationMetadata={nodeInformationMetadata}
        />
      </div>
    )
  );
}
