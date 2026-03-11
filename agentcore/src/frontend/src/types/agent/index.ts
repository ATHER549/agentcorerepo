import type { Edge, Node, reactFlowJsonObject } from "@xyflow/react";
import type { BuildStatus } from "../../constants/enums";
import type { APIClassType, OutputFieldType } from "../api/index";

export type PaginatedAgentsType = {
  items: AgentType[];
  total: number;
  size: number;
  page: number;
  pages: number;
};

export type AgentType = {
  name: string;
  id: string;
  data: reactFlowJsonObject<AllNodeType, EdgeType> | null;
  description: string;
  endpoint_name?: string | null;
  style?: AgentStyleType;
  is_component?: boolean;
  last_tested_version?: string;
  updated_at?: string;
  date_created?: string;
  parent?: string;
  folder?: string;
  user_id?: string;
  icon?: string;
  gradient?: string;
  tags?: string[];
  icon_bg_color?: string;
  project_id?: string;
  webhook?: boolean;
  locked?: boolean | null;
  public?: boolean;
  access_type?: "PUBLIC" | "PRIVATE" | "PROTECTED";
};

export type GenericNodeType = Node<NodeDataType, "genericNode">;
export type NoteNodeType = Node<NoteDataType, "noteNode">;

export type AllNodeType = GenericNodeType | NoteNodeType;
export type SetNodeType<T = "genericNode" | "noteNode"> =
  T extends "genericNode" ? GenericNodeType : NoteNodeType;

export type noteClassType = Pick<
  APIClassType,
  "description" | "display_name" | "documentation" | "tool_mode" | "frozen"
> & {
  template: {
    backgroundColor?: string;
    [key: string]: any;
  };
  outputs?: OutputFieldType[];
};

export type NoteDataType = {
  showNode?: boolean;
  type: string;
  node: noteClassType;
  id: string;
};
export type NodeDataType = {
  showNode?: boolean;
  type: string;
  node: APIClassType;
  id: string;
  output_types?: string[];
  selected_output_type?: string;
  buildStatus?: BuildStatus;
  selected_output?: string;
};

export type EdgeType = Edge<EdgeDataType, "default">;

export type EdgeDataType = {
  sourceHandle: sourceHandleType;
  targetHandle: targetHandleType;
};

// AgentStyleType is the type of the style object that is used to style the
// agent card with an emoji and a color.
export type AgentStyleType = {
  emoji: string;
  color: string;
  agent_id: string;
};

export type TweaksType = Array<
  {
    [key: string]: {
      output_key?: string;
    };
  } & AgentStyleType
>;

// right side
export type sourceHandleType = {
  baseClasses?: string[];
  dataType: string;
  id: string;
  output_types: string[];
  conditionalPath?: string | null;
  name: string;
};
//left side
export type targetHandleType = {
  inputTypes?: string[];
  output_types?: string[];
  type: string;
  fieldName: string;
  name?: string;
  id: string;
  proxy?: { field: string; id: string };
};
