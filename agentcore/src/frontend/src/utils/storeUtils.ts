import type { Node } from "@xyflow/react";
import { cloneDeep, uniqueId } from "lodash";
import type { AgentType, NodeDataType } from "../types/agent";
import { isInputNode, isOutputNode } from "./reactFlowUtils";

export default function cloneFLowWithParent(
  agent: AgentType,
  parent: string,
  is_component: boolean,
  keepId = false,
) {
  const childFLow = cloneDeep(agent);
  childFLow.parent = parent;
  if (!keepId) {
    childFLow.id = "";
  } else {
    childFLow.id = uniqueId() + "-" + childFLow.id;
  }
  childFLow.is_component = is_component;
  return childFLow;
}

export function getInputsAndOutputs(nodes: Node[]) {
  const inputs: {
    type: string;
    id: string;
    displayName: string;
  }[] = [];
  const outputs: {
    type: string;
    id: string;
    displayName: string;
  }[] = [];
  nodes.forEach((node) => {
    const nodeData: NodeDataType = node.data as NodeDataType;
    if (isOutputNode(nodeData)) {
      outputs.push({
        type: nodeData.type,
        id: nodeData.id,
        displayName: nodeData.node?.display_name ?? nodeData.id,
      });
    }
    if (isInputNode(nodeData)) {
      inputs.push({
        type: nodeData.type,
        id: nodeData.id,
        displayName: nodeData.node?.display_name ?? nodeData.id,
      });
    }
  });
  return { inputs, outputs };
}
